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

Total: 7 tests
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

client_service = ClientService()
reader_service = ReaderService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
fault_code_service = FaultCodeService()
mobile_service = MobileService()

# The keys the contract defines, exactly
PACKAGE_KEYS = {
    'id', 'folder_number', 'folder_name', 'client_name', 'period_year',
    'period_number', 'reader_id', 'walk_order_start', 'walk_order_end',
    'include_previous_readings', 'meters',
}
METER_KEYS = {
    'meter_number', 'customer_number', 'customer_name', 'address',
    'walk_order', 'previous_reading', 'manager_notes',
}


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

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()


if __name__ == "__main__":
    main()