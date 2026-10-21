"""
Monim : Mobile Service Tests
Testing the download payload the reader's mobile app receives (WP3 API contract).

Tests Summary:

1. Download Payload (7 tests)
   - Payload structure matches the contract (fault codes + package fields)
   - Meters in contract format, previous_reading as float, JSON-serializable
   - Download marks the folder: in_progress, and not sent again
   - Folder released without previous readings sends previous_reading as None
   - A folder that was not released is not included
   - Unknown reader (blocked)
   - Only active fault codes are sent

2. Receive One Reading (10 tests)
   - Regular reading: saved, meter completed, progress, folder in progress
   - Fault code only: kept, meter still completed
   - Same version twice: saved once, no double progress
   - Correction (new version): history kept, meter updated, code cleared
   - Verified exception: meter exception, reading waits for review, no progress
   - No-reading: no value, reason and notes kept, meter exception
   - Photo missing on a regular reading: flagged, meter still completed
   - Invalid data (6 cases): rejected, nothing written
   - Completed then corrected to an exception: folder progress goes back down
   - Same version_id twice: blocked by the database (UniqueViolation)

3. Meter Added In The Field (4 tests)
   - Created without source file or row, marked, folder count updated
   - Existing meter number in the period (blocked)
   - Folder from another period (blocked)
   - A field meter receives a reading like any meter (progress 1/3)

4. Receive A Batch (9 tests)
   - Batch of two: both accepted in order; field time stored as local time
   - Same batch twice: accepted again, nothing saved twice
   - One bad reading does not fail the others (invalid_data, meter_not_found)
   - Meter in another folder: meter_not_in_package / meter_exists_in_other_folder
   - New meter from the field: created once, reading accepted, folder 1/3
   - new_meter for a meter already in this folder: a regular reading
   - Reading with a photo: file saved, one photo record even after a retransmission
   - Photo flagged but not sent: missing_photo, nothing written
   - Unknown package: the whole request fails

Total: 36 tests
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.test_helpers import report, print_summary, cleanup, reset_counters
from src.services.client_service import ClientService
from src.services.reader_service import ReaderService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.workfolder_service import WorkFolderService
from src.services.fault_code_service import FaultCodeService
from src.services.mobile_service import MobileService
from datetime import datetime
from src.services.reading_service import ReadingService
from psycopg2 import errors as pg_errors
import tempfile, shutil
from datetime import timezone

client_service = ClientService()
reader_service = ReaderService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
fault_code_service = FaultCodeService()
PHOTO_DIR = tempfile.mkdtemp(prefix='monim_photos_')
mobile_service = MobileService(photo_dir=PHOTO_DIR)  # Photos go to a temporary folder
reading_service = ReadingService()

READ_AT = datetime(2026, 10, 21, 9, 30)  # When the reading was taken in the field

# The keys the contract defines, exactly
PACKAGE_KEYS = {
    'id', 'folder_number', 'folder_name', 'client_name', 'period_year', 'period_number', 'reader_id', 'walk_order_start', 'walk_order_end',
    'include_previous_readings', 'meters',}
METER_KEYS = { 'meter_number', 'customer_number', 'customer_name', 'address', 'walk_order', 'previous_reading', 'manager_notes',}

# HELPERS

def default_meter_rows():
    """Helper: two meters in walk order range 1000-2000"""
    return [
        {'row_number': 1, 'meter_number': 'MTR-MOB-001', 'customer_number': '40021',
         'customer_name': 'ישראל ישראלי', 'address': 'הרצל 12', 'walk_order': 1200,
         'previous_reading': 1234.5, 'installation_date': '2020-01-01', 'raw_data': {}},
        {'row_number': 2, 'meter_number': 'MTR-MOB-002', 'customer_number': '40022',
         'customer_name': 'דוד כהן', 'address': 'הרצל 14', 'walk_order': 1300,
         'previous_reading': 980, 'installation_date': '2020-01-01', 'raw_data': {}},
    ]

def create_folder_for_reader(corp_number, reader_username, release=True, include_previous=True):
    """
    Helper: a fresh client with one folder (two meters) assigned to a new reader,
    and released to the reader unless release=False. Returns (folder, reader).
    """
    rc = client_service.create_client(f"עיריית מובייל {corp_number}", corp_number)
    rp = period_service.initialize_periods_for_year(rc['client_id'], 2026)[0]
    template_service.create_template(rc['client_id'], 3, "שכונת הדר", 1000, 2000)

    sf = source_file_service.upload_period_file(
        period_id=rp['period_id'], original_filename="mobile.xlsx", file_type="excel")
    meter_service.create_meters_from_parsed_rows(rp['period_id'], sf['source_file_id'], default_meter_rows())

    folder_service.create_folders_for_period(rp['period_id'])
    folder_service.distribute_meters_into_folders(rp['period_id'])
    folder = folder_service.get_period_folders(rp['period_id'])[0]

    reader = reader_service.create_reader("קורא מובייל", reader_username, "hash")
    folder_service.assign_reader_to_folder(folder['folder_id'], reader['reader_id'])

    if release:
        folder_service.release_folder(folder['folder_id'], include_previous_readings=include_previous)
    return folder, reader

def first_meter(folder):
    """Helper: the first meter (MTR-MOB-001, previous reading 1234.5) of a test folder"""
    return meter_service.get_meter_by_number(folder['period_id'], 'MTR-MOB-001')


# The read time the app sends (UTC), and what the server stores (local time)
READ_AT_UTC = '2026-10-21T06:30:00.000Z'
READ_AT_LOCAL = datetime(2026, 10, 21, 6, 30, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)

class FakeUpload:
    """Helper: stands in for Flask's FileStorage (has .filename and .save)"""
    def __init__(self, content=b'fake image', filename='m1.jpg'):
        self.content, self.filename = content, filename

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.content)

def reading_item(version_id, meter_number='MTR-MOB-001', **overrides):
    """Helper: one item of the transmit JSON list, as the app sends it"""
    item = {'version_id': version_id, 'meter_number': meter_number, 'is_no_reading': False,
            'current_reading': 1250.5, 'first_attempt_reading': None, 'exception_type': None,
            'fault_code': None, 'notes': None, 'has_photo': False, 'photo_missing': False,
            'read_at': READ_AT_UTC, 'latitude': None, 'longitude': None, 'new_meter': None}
    item.update(overrides)
    return item

def add_other_folder(folder):
    """Helper: a second folder in the same period, with meter MTR-MOB-OTHER (walk order 2500)"""
    period = period_service.get_period(folder['period_id'])
    template_service.create_template(period['client_id'], 4, "תיק אחר", 2001, 3000)
    sf = source_file_service.get_period_source_file(folder['period_id'])
    meter_service.create_meters_from_parsed_rows(folder['period_id'], sf['source_file_id'],
        [{'row_number': 3, 'meter_number': 'MTR-MOB-OTHER', 'walk_order': 2500}])
    folder_service.create_folders_for_period(folder['period_id'])
    folder_service.distribute_meters_into_folders(folder['period_id'])

#  1. DOWNLOAD PAYLOAD

def test_payload_structure():
    """מבנה התשובה תואם לחוזה: קודי תקלה + שדות התיק"""
    try:
        folder, reader = create_folder_for_reader("200000001", "mobile_reader_1")

        payload = mobile_service.get_download_payload(reader['reader_id'])

        assert set(payload.keys()) == {'fault_codes', 'packages'}
        assert len(payload['fault_codes']) > 0
        assert all(set(fc.keys()) == {'code', 'description'} for fc in payload['fault_codes'])

        assert len(payload['packages']) == 1
        package = payload['packages'][0]
        assert set(package.keys()) == PACKAGE_KEYS
        assert package['id'] == folder['folder_id']
        assert package['folder_number'] == 3
        assert package['folder_name'] == "שכונת הדר"
        assert package['client_name'] == "עיריית מובייל 200000001"
        assert package['period_year'] == 2026
        assert package['period_number'] == 1
        assert package['reader_id'] == reader['reader_id']
        assert package['walk_order_start'] == 1000
        assert package['walk_order_end'] == 2000
        assert package['include_previous_readings'] is True
        report("מבנה התשובה תואם לחוזה", True)
    except AssertionError as e:
        report("מבנה התשובה תואם לחוזה", False, str(e))

def test_meters_in_contract_format():
    """מונים בפורמט החוזה, קריאה קודמת כ-float, והכול ניתן להמרה ל-JSON"""
    try:
        _, reader = create_folder_for_reader("200000002", "mobile_reader_2")

        payload = mobile_service.get_download_payload(reader['reader_id'])
        meters = {m['meter_number']: m for m in payload['packages'][0]['meters']}

        assert set(meters.keys()) == {'MTR-MOB-001', 'MTR-MOB-002'}
        assert all(set(m.keys()) == METER_KEYS for m in meters.values())

        first = meters['MTR-MOB-001']
        assert first['customer_name'] == 'ישראל ישראלי'
        assert first['walk_order'] == 1200
        assert isinstance(first['previous_reading'], float)  # Not Decimal
        assert first['previous_reading'] == 1234.5
        assert meters['MTR-MOB-002']['previous_reading'] == 980.0

        json.dumps(payload)  # Would raise TypeError on a Decimal or a date
        report("מונים בפורמט החוזה + JSON תקין", True)
    except (AssertionError, TypeError) as e:
        report("מונים בפורמט החוזה + JSON תקין", False, str(e))

def test_download_marks_folder():
    """הורדה מסמנת את התיק: in_progress, ולא נשלח שוב"""
    try:
        folder, reader = create_folder_for_reader("200000003", "mobile_reader_3")

        mobile_service.get_download_payload(reader['reader_id'])

        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['downloaded_at'] is not None
        assert updated['status'] == 'in_progress'

        second = mobile_service.get_download_payload(reader['reader_id'])
        assert second['packages'] == []
        assert len(second['fault_codes']) > 0  # Fault codes come on every download
        report("הורדה מסמנת את התיק ולא שולחת שוב", True)
    except AssertionError as e:
        report("הורדה מסמנת את התיק ולא שולחת שוב", False, str(e))

def test_without_previous_readings():
    """תיק ששוחרר בלי קריאה קודמת - previous_reading הוא None"""
    try:
        _, reader = create_folder_for_reader("200000004", "mobile_reader_4", include_previous=False)

        payload = mobile_service.get_download_payload(reader['reader_id'])
        package = payload['packages'][0]

        assert package['include_previous_readings'] is False
        assert all(m['previous_reading'] is None for m in package['meters'])
        report("בלי קריאה קודמת - previous_reading הוא None", True)
    except AssertionError as e:
        report("בלי קריאה קודמת - previous_reading הוא None", False, str(e))

def test_unreleased_folder_not_included():
    """תיק משויך שלא שוחרר - לא נשלח ולא מסומן"""
    try:
        folder, reader = create_folder_for_reader("200000005", "mobile_reader_5", release=False)

        payload = mobile_service.get_download_payload(reader['reader_id'])

        assert payload['packages'] == []
        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['downloaded_at'] is None
        assert updated['status'] == 'assigned'
        report("תיק לא משוחרר - לא נשלח", True)
    except AssertionError as e:
        report("תיק לא משוחרר - לא נשלח", False, str(e))

def test_unknown_reader_blocked():
    """קורא שלא קיים - חסום"""
    try:
        mobile_service.get_download_payload(99999)
        report("קורא לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("קורא לא קיים (חסום)", True)
        except AssertionError as ae:
            report("קורא לא קיים (חסום)", False, str(ae))

def test_only_active_fault_codes():
    """רק קודי תקלה פעילים נשלחים"""
    try:
        _, reader = create_folder_for_reader("200000006", "mobile_reader_6")

        payload = mobile_service.get_download_payload(reader['reader_id'])

        sent = {fc['code'] for fc in payload['fault_codes']}
        active = {fc['code'] for fc in fault_code_service.list_active()}
        assert sent == active
        report("רק קודי תקלה פעילים", True)
    except AssertionError as e:
        report("רק קודי תקלה פעילים", False, str(e))

#  2. RECEIVE ONE READING (ReadingService.receive_mobile_reading)

def test_receive_regular_reading():
    """קריאה רגילה: נשמרת, המונה הושלם, ההתקדמות עולה, התיק בביצוע"""
    try:
        folder, reader = create_folder_for_reader("200000011", "mobile_reader_11")
        meter = first_meter(folder)

        result = reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-reg-1',
            is_no_reading=False, current_reading=1250.5, notes='ליד השער', read_at=READ_AT)

        assert result['already_received'] is False
        reading = result['reading']
        assert reading['reading_status'] == 'approved'
        assert reading['version_id'] == 'v-reg-1'
        assert reading['notes'] == 'ליד השער'
        assert reading['reading_time'] == READ_AT  # Field time, not server time
        assert reading['transmitted_at'] is not None

        updated = meter_service.get_meter(meter['period_meter_id'])
        assert float(updated['current_reading']) == 1250.5
        assert float(updated['consumption']) == 16.0  # 1250.5 - 1234.5
        assert updated['work_status'] == 'completed'
        assert updated['manager_notes'] is None  # Reader notes never go here

        updated_folder = folder_service.get_folder(folder['folder_id'])
        assert updated_folder['completed_meters'] == 1
        assert updated_folder['status'] == 'in_progress'  # Was 'assigned' (not downloaded)
        report("קריאה רגילה - נשמרת, מונה הושלם, התקדמות", True)
    except AssertionError as e:
        report("קריאה רגילה - נשמרת, מונה הושלם, התקדמות", False, str(e))

def test_receive_reading_with_fault_code_only():
    """קריאה + קוד תקלה, בלי חריגה: הקוד נשמר, והמונה עדיין הושלם"""
    try:
        folder, reader = create_folder_for_reader("200000012", "mobile_reader_12")
        meter = first_meter(folder)

        result = reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-fault-1',
            is_no_reading=False, current_reading=1250.5, fault_code='14', read_at=READ_AT)

        assert result['reading']['reading_status'] == 'approved'
        updated = meter_service.get_meter(meter['period_meter_id'])
        assert updated['current_fault_code'] == '14'
        assert updated['work_status'] == 'completed'  # A fault code alone is not an exception
        report("קוד תקלה בלבד - נשמר, המונה הושלם (לא חריג)", True)
    except AssertionError as e:
        report("קוד תקלה בלבד - נשמר, המונה הושלם (לא חריג)", False, str(e))

def test_receive_same_version_twice():
    """אותה גרסה פעמיים (האישור לא הגיע): לא נשמרת שוב, וההתקדמות לא עולה פעמיים"""
    try:
        folder, reader = create_folder_for_reader("200000013", "mobile_reader_13")
        meter = first_meter(folder)
        args = dict(version_id='v-dup-1', is_no_reading=False, current_reading=1250.5, read_at=READ_AT)

        first = reading_service.receive_mobile_reading(meter['period_meter_id'], reader['reader_id'], **args)
        second = reading_service.receive_mobile_reading(meter['period_meter_id'], reader['reader_id'], **args)

        assert first['already_received'] is False
        assert second['already_received'] is True
        assert second['reading']['reading_id'] == first['reading']['reading_id']
        assert reading_service.count_meter_readings(meter['period_meter_id']) == 1
        assert folder_service.get_folder(folder['folder_id'])['completed_meters'] == 1
        report("אותה גרסה פעמיים - נשמרת פעם אחת", True)
    except AssertionError as e:
        report("אותה גרסה פעמיים - נשמרת פעם אחת", False, str(e))

def test_receive_correction_new_version():
    """תיקון (גרסה חדשה לאותו מונה): שורה נוספת ביומן, המונה מתעדכן, ההתקדמות לא עולה פעמיים"""
    try:
        folder, reader = create_folder_for_reader("200000014", "mobile_reader_14")
        meter = first_meter(folder)

        reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-cor-1',
            is_no_reading=False, current_reading=1250.5, fault_code='14', read_at=READ_AT)
        reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-cor-2',
            is_no_reading=False, current_reading=1260.0, read_at=READ_AT)

        assert reading_service.count_meter_readings(meter['period_meter_id']) == 2  # History kept
        updated = meter_service.get_meter(meter['period_meter_id'])
        assert float(updated['current_reading']) == 1260.0
        assert updated['current_fault_code'] is None  # The correction removed the code
        assert folder_service.get_folder(folder['folder_id'])['completed_meters'] == 1
        report("תיקון - שורה נוספת, מונה מתעדכן, בלי ספירה כפולה", True)
    except AssertionError as e:
        report("תיקון - שורה נוספת, מונה מתעדכן, בלי ספירה כפולה", False, str(e))

def test_receive_verified_exception():
    """חריגה מאומתת: המונה חריג, הקריאה ממתינה למנהל, ההתקדמות לא עולה"""
    try:
        folder, reader = create_folder_for_reader("200000015", "mobile_reader_15")
        meter = first_meter(folder)

        result = reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-exc-1',
            is_no_reading=False, current_reading=1520.0, first_attempt_reading=1520.0,
            exception_type='high', fault_code='30', read_at=READ_AT)

        reading = result['reading']
        assert reading['reading_status'] == 'requires_review'
        assert reading['exception_type'] == 'high'
        assert float(reading['first_attempt_reading']) == 1520.0

        updated = meter_service.get_meter(meter['period_meter_id'])
        assert updated['work_status'] == 'exception'
        assert float(updated['current_reading']) == 1520.0
        assert folder_service.get_folder(folder['folder_id'])['completed_meters'] == 0
        report("חריגה מאומתת - חריג, ממתין למנהל, בלי התקדמות", True)
    except AssertionError as e:
        report("חריגה מאומתת - חריג, ממתין למנהל, בלי התקדמות", False, str(e))

def test_receive_no_reading():
    """אי-קריאה: נשמרת בלי ערך, עם הסיבה וההערה, והמונה חריג"""
    try:
        folder, reader = create_folder_for_reader("200000016", "mobile_reader_16")
        meter = first_meter(folder)

        result = reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-noread-1',
            is_no_reading=True, fault_code='13', notes='כלב בחצר', read_at=READ_AT)

        reading = result['reading']
        assert reading['is_no_reading'] is True
        assert reading['current_reading'] is None
        assert reading['consumption'] is None
        assert reading['fault_code'] == '13'
        assert reading['notes'] == 'כלב בחצר'
        assert reading['reading_status'] == 'requires_review'

        updated = meter_service.get_meter(meter['period_meter_id'])
        assert updated['work_status'] == 'exception'
        assert updated['current_reading'] is None  # Never read
        assert updated['current_fault_code'] == '13'
        assert updated['manager_notes'] is None
        report("אי-קריאה - בלי ערך, עם סיבה, מונה חריג", True)
    except AssertionError as e:
        report("אי-קריאה - בלי ערך, עם סיבה, מונה חריג", False, str(e))

def test_receive_photo_missing_is_not_exception():
    """תמונה חסרה בקריאה רגילה: מסומנת, אבל המונה עדיין הושלם"""
    try:
        folder, reader = create_folder_for_reader("200000017", "mobile_reader_17")
        meter = first_meter(folder)

        result = reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-photo-1',
            is_no_reading=False, current_reading=1250.5, photo_missing=True, read_at=READ_AT)

        assert result['reading']['photo_missing'] is True
        assert result['reading']['reading_status'] == 'approved'
        assert meter_service.get_meter(meter['period_meter_id'])['work_status'] == 'completed'
        report("תמונה חסרה - מסומנת, לא חריג", True)
    except AssertionError as e:
        report("תמונה חסרה - מסומנת, לא חריג", False, str(e))

def test_receive_invalid_data_writes_nothing():
    """קלט לא תקין: נזרקת שגיאה, ושום דבר לא נכתב"""
    folder, reader = create_folder_for_reader("200000018", "mobile_reader_18")
    meter = first_meter(folder)
    meter_id = meter['period_meter_id']

    cases = [
        ("אי-קריאה עם ערך", dict(is_no_reading=True, current_reading=100.0, fault_code='13')),
        ("אי-קריאה בלי קוד", dict(is_no_reading=True)),
        ("קריאה רגילה בלי ערך", dict(is_no_reading=False)),
        ("חריגה בלי קוד תקלה", dict(is_no_reading=False, current_reading=1520.0, exception_type='high')),
        ("סוג חריגה לא קיים", dict(is_no_reading=False, current_reading=1520.0, exception_type='huge', fault_code='30')),
    ]
    for i, (label, args) in enumerate(cases):
        try:
            reading_service.receive_mobile_reading(
                meter_id, reader['reader_id'], version_id=f'v-bad-{i}', read_at=READ_AT, **args)
            report(f"קלט לא תקין: {label}", False, "לא נזרקה שגיאה")
        except ValueError:
            report(f"קלט לא תקין: {label} (חסום)", True)

    try:
        reading_service.receive_mobile_reading(
            meter_id, reader['reader_id'], version_id=None,
            is_no_reading=False, current_reading=1250.5, read_at=READ_AT)
        report("קלט לא תקין: בלי מזהה גרסה", False, "לא נזרקה שגיאה")
    except ValueError:
        report("קלט לא תקין: בלי מזהה גרסה (חסום)", True)

    try:
        assert reading_service.count_meter_readings(meter_id) == 0
        assert meter_service.get_meter(meter_id)['work_status'] == 'assigned_to_reader'  # Untouched
        report("קלט לא תקין - שום דבר לא נכתב", True)
    except AssertionError as e:
        report("קלט לא תקין - שום דבר לא נכתב", False, str(e))

def test_completed_then_exception_recounts_progress():
    """מונה שהושלם ותוקן לחריג: ההתקדמות של התיק יורדת חזרה"""
    try:
        folder, reader = create_folder_for_reader("200000019", "mobile_reader_19")
        meter = first_meter(folder)

        reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-recount-1',
            is_no_reading=False, current_reading=1250.5, read_at=READ_AT)
        assert folder_service.get_folder(folder['folder_id'])['completed_meters'] == 1

        reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-recount-2',
            is_no_reading=True, fault_code='13', read_at=READ_AT)

        assert meter_service.get_meter(meter['period_meter_id'])['work_status'] == 'exception'
        assert folder_service.get_folder(folder['folder_id'])['completed_meters'] == 0
        report("הושלם ואז חריג - ההתקדמות מתעדכנת", True)
    except AssertionError as e:
        report("הושלם ואז חריג - ההתקדמות מתעדכנת", False, str(e))

def test_same_version_blocked_by_database():
    """רשת הביטחון: ה-DB עצמו חוסם שורה שנייה עם אותו version_id (UniqueViolation)"""
    folder, reader = create_folder_for_reader("200000020", "mobile_reader_20")
    meter = first_meter(folder)
    row = dict(period_meter_id=meter['period_meter_id'], reader_id=reader['reader_id'],
               previous_reading=None, current_reading=100.0, consumption=None,
               version_id='v-unique-1')

    reading_service.repo.create(**row)
    try:
        reading_service.repo.create(**row)
        report("UNIQUE על version_id", False, "לא נזרקה שגיאה")
    except pg_errors.UniqueViolation:
        report("UNIQUE על version_id (חסום, UniqueViolation)", True)
    except Exception as e:
        report("UNIQUE על version_id", False, f"נזרק {type(e).__name__} ולא UniqueViolation")

#  3. METER ADDED IN THE FIELD (PeriodMeterService.create_field_meter)

def test_create_field_meter():
    """מונה מהשטח: בלי קובץ ושורה, מסומן, בתיק של הקורא, והספירה של התיק מתעדכנת"""
    try:
        folder, _ = create_folder_for_reader("200000021", "mobile_reader_21")

        meter = meter_service.create_field_meter(
            folder['period_id'], folder['folder_id'], " 99887766 ",
            customer_name="דוד כהן", address="הרצל 14", walk_order=1206)

        assert meter['meter_number'] == "99887766"  # Trimmed
        assert meter['added_in_field'] is True
        assert meter['source_file_id'] is None
        assert meter['row_number'] is None
        assert meter['folder_id'] == folder['folder_id']
        assert meter['work_status'] == 'assigned_to_reader'
        assert meter['customer_name'] == "דוד כהן"
        assert meter['walk_order'] == 1206

        # The caller refreshes the folder counts: 2 meters from the file + 1 from the field
        folder_service.update_folder_progress(folder['folder_id'])
        assert folder_service.get_folder(folder['folder_id'])['total_meters'] == 3
        report("מונה מהשטח - נוצר, מסומן, ספירת התיק 3", True)
    except AssertionError as e:
        report("מונה מהשטח - נוצר, מסומן, ספירת התיק 3", False, str(e))

def test_create_field_meter_existing_number_blocked():
    """מונה מהשטח עם מספר שכבר קיים בתקופה - חסום"""
    folder, _ = create_folder_for_reader("200000022", "mobile_reader_22")
    try:
        meter_service.create_field_meter(folder['period_id'], folder['folder_id'], "MTR-MOB-001")
        report("מונה מהשטח עם מספר קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "כבר קיים" in str(e)
            report("מונה מהשטח עם מספר קיים (חסום)", True)
        except AssertionError as ae:
            report("מונה מהשטח עם מספר קיים (חסום)", False, str(ae))

def test_create_field_meter_folder_of_other_period_blocked():
    """מונה מהשטח לתיק מתקופה אחרת - חסום"""
    folder_a, _ = create_folder_for_reader("200000023", "mobile_reader_23")
    folder_b, _ = create_folder_for_reader("200000024", "mobile_reader_24")
    try:
        meter_service.create_field_meter(folder_a['period_id'], folder_b['folder_id'], "99887766")
        report("מונה מהשטח לתיק מתקופה אחרת", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא שייך" in str(e)
            report("מונה מהשטח לתיק מתקופה אחרת (חסום)", True)
        except AssertionError as ae:
            report("מונה מהשטח לתיק מתקופה אחרת (חסום)", False, str(ae))

def test_field_meter_can_receive_a_reading():
    """מונה מהשטח מקבל קריאה כמו כל מונה, וההתקדמות נספרת מתוך 3"""
    try:
        folder, reader = create_folder_for_reader("200000025", "mobile_reader_25")
        meter = meter_service.create_field_meter(folder['period_id'], folder['folder_id'], "99887766")
        folder_service.update_folder_progress(folder['folder_id'])

        result = reading_service.receive_mobile_reading(
            meter['period_meter_id'], reader['reader_id'], version_id='v-field-1',
            is_no_reading=False, current_reading=310.0, read_at=READ_AT)

        assert result['reading']['reading_status'] == 'approved'
        assert result['reading']['consumption'] is None  # No previous reading for a new meter
        updated_folder = folder_service.get_folder(folder['folder_id'])
        assert updated_folder['completed_meters'] == 1
        assert updated_folder['total_meters'] == 3
        report("מונה מהשטח מקבל קריאה - 1/3", True)
    except AssertionError as e:
        report("מונה מהשטח מקבל קריאה - 1/3", False, str(e))

#  4. RECEIVE A BATCH (MobileService.receive_readings)

def test_batch_of_readings_accepted():
    """מנה של שתי קריאות: שתיהן מתקבלות, בסדר שנשלחו, וזמן השטח מומר לשעון מקומי"""
    try:
        folder, _ = create_folder_for_reader("200000031", "mobile_reader_31")

        response = mobile_service.receive_readings(folder['folder_id'], [
            reading_item('v-batch-1'),
            reading_item('v-batch-2', meter_number='MTR-MOB-002', current_reading=990.0),
        ], photos={})

        assert response == {'results': [
            {'version_id': 'v-batch-1', 'status': 'accepted'},
            {'version_id': 'v-batch-2', 'status': 'accepted'},
        ]}
        meter = first_meter(folder)
        assert meter['work_status'] == 'completed'
        reading = reading_service.get_latest_meter_reading(meter['period_meter_id'])
        assert reading['reading_time'] == READ_AT_LOCAL  # 06:30Z → local time
        assert folder_service.get_folder(folder['folder_id'])['completed_meters'] == 2
        report("מנה של שתי קריאות - שתיהן מתקבלות", True)
    except AssertionError as e:
        report("מנה של שתי קריאות - שתיהן מתקבלות", False, str(e))

def test_batch_sent_twice():
    """אותה מנה פעמיים: גם בפעם השנייה accepted, ושום דבר לא נשמר פעמיים"""
    try:
        folder, _ = create_folder_for_reader("200000032", "mobile_reader_32")
        batch = [reading_item('v-twice-1')]

        mobile_service.receive_readings(folder['folder_id'], batch, photos={})
        second = mobile_service.receive_readings(folder['folder_id'], batch, photos={})

        assert second['results'][0]['status'] == 'accepted'
        assert reading_service.count_meter_readings(first_meter(folder)['period_meter_id']) == 1
        report("אותה מנה פעמיים - accepted, נשמר פעם אחת", True)
    except AssertionError as e:
        report("אותה מנה פעמיים - accepted, נשמר פעם אחת", False, str(e))

def test_one_bad_reading_does_not_fail_the_others():
    """קריאה לא תקינה ומונה לא קיים נדחים, והקריאה התקינה באותה מנה מתקבלת"""
    try:
        folder, _ = create_folder_for_reader("200000033", "mobile_reader_33")

        response = mobile_service.receive_readings(folder['folder_id'], [
            reading_item('v-mix-1', is_no_reading=True, current_reading=100.0, fault_code='13'),
            reading_item('v-mix-2', meter_number='NO-SUCH-METER'),
            reading_item('v-mix-3', meter_number='MTR-MOB-002'),
        ], photos={})

        results = response['results']
        assert results[0] == {'version_id': 'v-mix-1', 'status': 'rejected', 'reason': 'invalid_data'}
        assert results[1] == {'version_id': 'v-mix-2', 'status': 'rejected', 'reason': 'meter_not_found'}
        assert results[2] == {'version_id': 'v-mix-3', 'status': 'accepted'}
        assert reading_service.count_meter_readings(first_meter(folder)['period_meter_id']) == 0
        report("קריאה רעה לא מפילה את המנה", True)
    except AssertionError as e:
        report("קריאה רעה לא מפילה את המנה", False, str(e))

def test_meter_in_another_folder():
    """מונה מתיק אחר: בלי new_meter - meter_not_in_package, עם new_meter - meter_exists_in_other_folder"""
    try:
        folder, _ = create_folder_for_reader("200000034", "mobile_reader_34")
        add_other_folder(folder)

        response = mobile_service.receive_readings(folder['folder_id'], [
            reading_item('v-other-1', meter_number='MTR-MOB-OTHER'),
            reading_item('v-other-2', meter_number='MTR-MOB-OTHER', new_meter={'customer_name': 'x'}),
        ], photos={})

        assert response['results'][0]['reason'] == 'meter_not_in_package'
        assert response['results'][1]['reason'] == 'meter_exists_in_other_folder'
        other = meter_service.get_meter_by_number(folder['period_id'], 'MTR-MOB-OTHER')
        assert reading_service.count_meter_readings(other['period_meter_id']) == 0
        report("מונה מתיק אחר - נדחה עם הסיבה הנכונה", True)
    except AssertionError as e:
        report("מונה מתיק אחר - נדחה עם הסיבה הנכונה", False, str(e))

def test_new_meter_from_the_field():
    """new_meter עם מספר חדש: המונה נוצר בתיק, והקריאה מתקבלת. שידור חוזר לא יוצר אותו שוב"""
    try:
        folder, _ = create_folder_for_reader("200000035", "mobile_reader_35")
        batch = [reading_item('v-new-1', meter_number='99887766', current_reading=310.0,
                              new_meter={'customer_name': 'דוד כהן', 'address': 'הרצל 14',
                                         'customer_number': None, 'walk_order': 1206})]

        first = mobile_service.receive_readings(folder['folder_id'], batch, photos={})
        mobile_service.receive_readings(folder['folder_id'], batch, photos={})  # Retransmission

        assert first['results'][0]['status'] == 'accepted'
        meter = meter_service.get_meter_by_number(folder['period_id'], '99887766')
        assert meter['added_in_field'] is True
        assert meter['customer_name'] == 'דוד כהן'
        assert reading_service.count_meter_readings(meter['period_meter_id']) == 1
        updated_folder = folder_service.get_folder(folder['folder_id'])
        assert updated_folder['total_meters'] == 3
        assert updated_folder['completed_meters'] == 1
        report("מונה מהשטח - נוצר פעם אחת, הקריאה מתקבלת", True)
    except AssertionError as e:
        report("מונה מהשטח - נוצר פעם אחת, הקריאה מתקבלת", False, str(e))

def test_new_meter_already_in_this_folder():
    """new_meter למונה שכבר בתיק: קריאה רגילה למונה הקיים, בלי ליצור מונה"""
    try:
        folder, _ = create_folder_for_reader("200000036", "mobile_reader_36")

        response = mobile_service.receive_readings(folder['folder_id'], [
            reading_item('v-same-1', new_meter={'customer_name': 'x'})], photos={})

        assert response['results'][0]['status'] == 'accepted'
        assert len(meter_service.get_folder_meters(folder['folder_id'])) == 2  # No new meter
        assert first_meter(folder)['work_status'] == 'completed'
        report("new_meter למונה שכבר בתיק - קריאה רגילה", True)
    except AssertionError as e:
        report("new_meter למונה שכבר בתיק - קריאה רגילה", False, str(e))

def test_reading_with_photo():
    """קריאה עם תמונה: הקובץ נשמר, ורשומה אחת ב-photos, גם אחרי שידור חוזר"""
    try:
        folder, _ = create_folder_for_reader("200000037", "mobile_reader_37")
        batch = [reading_item('v-pic-1', has_photo=True)]
        photos = {'photo_MTR-MOB-001': FakeUpload()}

        response = mobile_service.receive_readings(folder['folder_id'], batch, photos)
        mobile_service.receive_readings(folder['folder_id'], batch, photos)  # Retransmission

        assert response['results'][0]['status'] == 'accepted'
        reading = reading_service.get_latest_meter_reading(first_meter(folder)['period_meter_id'])
        photo_rows = mobile_service.photo_service.get_reading_photos(reading['reading_id'])
        assert len(photo_rows) == 1
        assert os.path.exists(photo_rows[0]['photo_path'])
        assert photo_rows[0]['photo_path'].endswith('v-pic-1.jpg')
        report("קריאה עם תמונה - קובץ ורשומה אחת", True)
    except AssertionError as e:
        report("קריאה עם תמונה - קובץ ורשומה אחת", False, str(e))

def test_photo_flagged_but_not_sent():
    """has_photo בלי קובץ בבקשה: missing_photo, ושום דבר לא נכתב"""
    try:
        folder, _ = create_folder_for_reader("200000038", "mobile_reader_38")

        response = mobile_service.receive_readings(folder['folder_id'], [
            reading_item('v-nopic-1', has_photo=True)], photos={})

        assert response['results'][0] == {'version_id': 'v-nopic-1', 'status': 'rejected', 'reason': 'missing_photo'}
        assert first_meter(folder)['work_status'] == 'assigned_to_reader'
        report("תמונה מסומנת שלא הגיעה - missing_photo", True)
    except AssertionError as e:
        report("תמונה מסומנת שלא הגיעה - missing_photo", False, str(e))

def test_unknown_package_fails_the_request():
    """תיק שלא קיים - כל הבקשה נכשלת"""
    try:
        mobile_service.receive_readings(99999, [reading_item('v-x-1')], photos={})
        report("תיק לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("תיק לא קיים (חסום)", True)
        except AssertionError as ae:
            report("תיק לא קיים (חסום)", False, str(ae))

#  RUN ALL TESTS

def main():
    reset_counters()

    print("=" * 50)
    print("  Monim tests: Mobile Service Tests")
    print("=" * 50)

    try:
        # 1. Download payload
        print("\n=== בדיקות תשובת ההורדה ===")
        test_payload_structure()
        test_meters_in_contract_format()
        test_download_marks_folder()
        test_without_previous_readings()
        test_unreleased_folder_not_included()
        test_unknown_reader_blocked()
        test_only_active_fault_codes()

        # 2. Receive one reading
        print("\n=== בדיקות קבלת קריאה ===")
        test_receive_regular_reading()
        test_receive_reading_with_fault_code_only()
        test_receive_same_version_twice()
        test_receive_correction_new_version()
        test_receive_verified_exception()
        test_receive_no_reading()
        test_receive_photo_missing_is_not_exception()
        test_receive_invalid_data_writes_nothing()
        test_completed_then_exception_recounts_progress()
        test_same_version_blocked_by_database()

        # 3. Meter added in the field
        print("\n=== בדיקות מונה מהשטח ===")
        test_create_field_meter()
        test_create_field_meter_existing_number_blocked()
        test_create_field_meter_folder_of_other_period_blocked()
        test_field_meter_can_receive_a_reading()

        # 4. Receive a batch
        print("\n=== בדיקות קבלת מנה ===")
        test_batch_of_readings_accepted()
        test_batch_sent_twice()
        test_one_bad_reading_does_not_fail_the_others()
        test_meter_in_another_folder()
        test_new_meter_from_the_field()
        test_new_meter_already_in_this_folder()
        test_reading_with_photo()
        test_photo_flagged_but_not_sent()
        test_unknown_package_fails_the_request()

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()
        shutil.rmtree(PHOTO_DIR, ignore_errors=True)  # Remove the test photos


if __name__ == "__main__":
    main()