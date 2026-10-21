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

Total: 11 tests
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

client_service = ClientService()
reader_service = ReaderService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
fault_code_service = FaultCodeService()
mobile_service = MobileService()
reading_service = ReadingService()

READ_AT = datetime(2026, 10, 21, 9, 30)  # When the reading was taken in the field

# The keys the contract defines, exactly
PACKAGE_KEYS = {
    'id', 'folder_number', 'folder_name', 'client_name', 'period_year', 'period_number', 'reader_id', 'walk_order_start', 'walk_order_end',
    'include_previous_readings', 'meters',}
METER_KEYS = { 'meter_number', 'customer_number', 'customer_name', 'address', 'walk_order', 'previous_reading', 'manager_notes',}


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

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()


if __name__ == "__main__":
    main()