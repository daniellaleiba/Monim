"""
Monim - process_uploaded_file Integration Test
Testing the FULL FLOW through PeriodSourceFileService.process_uploaded_file().

    process_uploaded_file(source_file_id)
        → finds file record in DB
        → picks parser by file_type
        → parses file
        → creates period_meters
        → updates statuses (source_file → success, period → active)

This is the production flow.

Note: Uses monim_v2_test DB. Cleanup in finally block.

Tests Summary:

1. Happy Path (10 tests)
   - process_uploaded_file succeeds
   - source_file status → 'success'
   - source_file rows_count updated
   - period status → 'active'
   - period_meters created in DB
   - meter data matches source file
   - all meters split correctly between 'new' and 'missing_info'
   - status summary matches (9 new, 1 missing_info)
   - meter with missing walk_order stored correctly
   - meter with a numeric meter_number in the source file stored as string

2. Error Handling (3 tests)
   - Processing file with bad path → error status
   - Error message saved in source_file
   - No partial meters left after failure

3. Retry (2 tests)
   - retry_processing cleans up and reprocesses
   - After retry: meters created, status success

4. Missing meter_number (3 tests)
   - Row without meter_number is skipped, processing still succeeds
   - Correct meter count after skip
   - Error message documents the skipped row

5. Missing Optional Fields (5 tests)
   - All rows imported even with missing optional fields
   - Rows missing optional fields marked 'missing_info'
   - missing_fields listed in raw_data
   - Normal rows stay 'new'
   - File status stays 'success' (missing fields don't count as skipped)

6. Partial Status (3 tests)
   - Over 5% skipped rows → status='partial'
   - Correct meter count after partial skip
   - Error message documents the skip ratio

Total: 26 tests
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# IMPORTANT: Override DB before any service imports
os.environ['DB_NAME'] = 'monim_v2_test'

from src.services.client_service import ClientService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from tests.test_helpers import report, print_summary, cleanup

# --- Services ---
client_service = ClientService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()

# --- Test file path ---
TEST_DIR = os.path.dirname(__file__)
SAMPLE_FILE = os.path.join(TEST_DIR, "test_data", "netanya_sample.xlsx")

# --- Shared state ---
test_client = None
test_period = None
test_source_file = None


#  1. HAPPY PATH : process_uploaded_file succeeds

def setup_happy_path():
    """Create client → period → source_file for happy path tests"""
    global test_client, test_period, test_source_file

    test_client = client_service.create_client("תאגיד בדיקת עיבוד", "800000001")
    print(f"  נוצר לקוח: {test_client['name']} (ID: {test_client['client_id']})")

    test_period = period_service.create_period(test_client['client_id'], 2026, 1)
    print(f"  נוצרה תקופה: {test_period['year']}/{test_period['period_number']} (ID: {test_period['period_id']})")

    test_source_file = source_file_service.upload_period_file(
        period_id=test_period['period_id'], original_filename="netanya_sample.xlsx",
        file_type="netanya_format", uploaded_by="test_script",
        file_path=SAMPLE_FILE)
    print(f"  נוצר קובץ מקור: {test_source_file['original_filename']} (ID: {test_source_file['source_file_id']})")
    print(f"  file_type: {test_source_file['file_type']}")
    print(f"  processing_status: {test_source_file['processing_status']}")

def test_process_uploaded_file_succeeds():
    """process_uploaded_file מסתיים בהצלחה"""
    try:
        result = source_file_service.process_uploaded_file(test_source_file['source_file_id'])
        print(f"    processing_status: {result['processing_status']}")
        print(f"    rows_count: {result['rows_count']}")
        report("process_uploaded_file הסתיים בהצלחה", True)
    except Exception as e:
        report("process_uploaded_file הסתיים בהצלחה", False, str(e))

def test_source_file_status_success():
    """סטטוס קובץ מקור → success"""
    sf = source_file_service.get_source_file(test_source_file['source_file_id'])
    print(f"    processing_status = '{sf['processing_status']}'")
    try:
        assert sf['processing_status'] == 'success'
        report("סטטוס קובץ מקור → 'success'", True)
    except AssertionError as e:
        report("סטטוס קובץ מקור → 'success'", False, str(e))

def test_source_file_rows_count():
    """rows_count עודכן במספר השורות"""
    sf = source_file_service.get_source_file(test_source_file['source_file_id'])
    print(f"    rows_count = {sf['rows_count']} (צפוי 10)")
    try:
        assert sf['rows_count'] == 10
        report("rows_count עודכן (10)", True)
    except AssertionError as e:
        report("rows_count עודכן (10)", False, str(e))

def test_period_status_active():
    """סטטוס תקופה → active"""
    period = period_service.get_period(test_period['period_id'])
    print(f"    period status = '{period['status']}'")
    try:
        assert period['status'] == 'active'
        report("סטטוס תקופה → 'active'", True)
    except AssertionError as e:
        report("סטטוס תקופה → 'active'", False, str(e))

def test_meters_created():
    """מונים נוצרו בDB"""
    count = meter_service.count_period_meters(test_period['period_id'])
    print(f"    מונים בDB = {count} (צפוי 10)")
    try:
        assert count == 10
        report("10 מונים נוצרו בDB", True)
    except AssertionError as e:
        report("10 מונים נוצרו בDB", False, str(e))

def test_meter_data_correct():
    """נתוני מונה ראשון תקינים"""
    meter = meter_service.get_meter_by_number(test_period['period_id'], '706D7E805DA846A3')
    if not meter:
        report("נתוני מונה ראשון", False, "לא נמצא")
        return

    print(f"    meter_number: {meter['meter_number']}")
    print(f"    address: {meter['address']}")
    print(f"    work_status: {meter['work_status']}")

    db_reading = float(meter['previous_reading']) if meter['previous_reading'] is not None else None

    try:
        assert meter['meter_number'] == '706D7E805DA846A3', f"meter_number={meter['meter_number']}"
        assert meter['address'] == 'ויצמן 14', f"address={meter['address']}"
        assert meter['work_status'] == 'new', f"work_status={meter['work_status']}"
        assert db_reading is not None and abs(db_reading - 147.437) < 0.001, f"previous_reading={db_reading}"
        assert meter['customer_number'] == '20433218196', f"customer_number={meter['customer_number']}"
        assert meter['walk_order'] == 105035029, f"walk_order={meter['walk_order']}"
        assert meter['source_file_id'] == test_source_file['source_file_id'], f"source_file_id={meter['source_file_id']}"
        report("נתוני מונה ראשון תקינים", True)
    except AssertionError as e:
        report("נתוני מונה ראשון תקינים", False, str(e))

def test_all_meters_status_new():
    """9 מהמונים בסטטוס new; 1 (שורה 5, בלי walk_order) ב-missing_info"""
    meters = meter_service.get_period_meters(test_period['period_id'])
    try:
        new_count = sum(1 for m in meters if m['work_status'] == 'new')
        missing_count = sum(1 for m in meters if m['work_status'] == 'missing_info')
        assert new_count == 9, f"new_count={new_count} (צפוי 9)"
        assert missing_count == 1, f"missing_count={missing_count} (צפוי 1)"
        report("9 מונים 'new' + 1 'missing_info' (walk_order חסר)", True)
    except AssertionError as e:
        report("9 מונים 'new' + 1 'missing_info' (walk_order חסר)", False, str(e))

def test_happy_path_status_summary():
    """סיכום סטטוסים תקין: 10 total, 9 new, 1 missing_info, 0 בתיקים/הושלמו"""
    summary = meter_service.get_period_status_summary(test_period['period_id'])
    print(f"    סיכום: {summary}")
    try:
        assert summary['total'] == 10, f"total={summary['total']} (צפוי 10)"
        assert summary['new'] == 9, f"new={summary['new']} (צפוי 9)"
        assert summary['missing_info'] == 1, f"missing_info={summary['missing_info']} (צפוי 1)"
        assert summary.get('assigned_to_folder', 0) == 0, "assigned_to_folder אמור להיות 0"
        assert summary.get('assigned_to_reader', 0) == 0, "assigned_to_reader אמור להיות 0"
        assert summary['completed'] == 0, "completed אמור להיות 0"
        report("סיכום סטטוסים תקין (9 new, 1 missing_info)", True)
    except AssertionError as e:
        report("סיכום סטטוסים תקין (9 new, 1 missing_info)", False, str(e))

def test_null_walk_order_meter():
    """מונה עם walk_order=None (שורה 5 בקובץ הדוגמה) נשמר כראוי"""
    meter = meter_service.get_meter_by_number(test_period['period_id'], '4F58D669CBEE3772')
    if not meter:
        report("מונה עם walk_order ריק", False, "לא נמצא")
        return

    print(f"    מונה {meter['meter_number']}: walk_order = {meter['walk_order']}")
    try:
        assert meter['walk_order'] is None
        report("מונה עם walk_order=None נשמר כראוי", True)
    except AssertionError as e:
        report("מונה עם walk_order=None נשמר כראוי", False, str(e))

def test_int_meter_number_stored_as_string():
    """מספר מונה שהיה int בקובץ המקורי (שורה 4) נשמר כ-string בDB"""
    # Row 4 has int meter_number (242053896) in the original file
    meter = meter_service.get_meter_by_number(test_period['period_id'], "118451462")
    if not meter:
        report("מונה עם מספר מספרי", False, "לא נמצא")
        return

    print(f"    מונה: meter_number = '{meter['meter_number']}' (type: {type(meter['meter_number']).__name__})")
    try:
        assert meter['meter_number'] == '118451462'
        assert isinstance(meter['meter_number'], str)
        report("מספר מונה מספרי נשמר כ-string בDB", True)
    except AssertionError as e:
        report("מספר מונה מספרי נשמר כ-string בDB", False, str(e))

#  2. ERROR HANDLING : bad file path

error_client = None
error_period = None
error_source_file = None

def setup_error_path():
    """Create source_file with a bad file path"""
    global error_client, error_period, error_source_file

    error_client = client_service.create_client("תאגיד בדיקת שגיאות", "800000002")
    error_period = period_service.create_period(error_client['client_id'], 2026, 1)

    error_source_file = source_file_service.upload_period_file(
        period_id=error_period['period_id'], original_filename="nonexistent.xlsx", file_type="netanya_format",
        uploaded_by="test_script", file_path="/fake/path/nonexistent.xlsx"  # קובץ שלא קיים
    )
    print(f"  נוצר קובץ מקור עם נתיב שגוי: {error_source_file['file_path']}")

def test_process_bad_file_marks_error():
    """עיבוד קובץ שלא קיים → סטטוס error"""
    try:
        source_file_service.process_uploaded_file(error_source_file['source_file_id'])
        report("קובץ לא קיים → error", False, "לא נזרקה שגיאה")
    except Exception:
        sf = source_file_service.get_source_file(error_source_file['source_file_id'])
        result = sf['processing_status'] == 'error'
        print(f"    processing_status = '{sf['processing_status']}'")
        report("קובץ לא קיים → סטטוס 'error'", result)

def test_error_message_saved():
    """הודעת שגיאה נשמרת ברשומת הקובץ"""
    sf = source_file_service.get_source_file(error_source_file['source_file_id'])
    print(f"    error_message = '{sf['error_message'][:80]}...'")
    try:
        assert sf['error_message'] is not None and len(sf['error_message']) > 0
        report("הודעת שגיאה נשמרה", True)
    except AssertionError as e:
        report("הודעת שגיאה נשמרה", False, str(e))

def test_no_partial_meters_after_error():
    """אין מונים חלקיים אחרי כישלון"""
    count = meter_service.count_period_meters(error_period['period_id'])
    print(f"    מונים בDB = {count} (צפוי 0)")
    try:
        assert count == 0
        report("אין מונים חלקיים אחרי כישלון", True)
    except AssertionError as e:
        report("אין מונים חלקיים אחרי כישלון", False, str(e))

#  3. RETRY : fix file and reprocess

def test_retry_processing_succeeds():
    """retry_processing עם נתיב מתוקן → הצלחה"""
    # First, fix the file path in DB so retry can find the file
    # We simulate "fixing" by replacing the file with the real one
    source_file_service.replace_period_file( period_id=error_period['period_id'], original_filename="netanya_sample_fixed.xlsx",
        file_type="netanya_format", uploaded_by="test_script", file_path=SAMPLE_FILE)

    # Now mark it as error again so retry_processing accepts it
    source_file_service.mark_processing_error(error_source_file['source_file_id'], "שגיאה מקורית")

    try:
        result = source_file_service.retry_processing(error_source_file['source_file_id'])
        print(f"    processing_status = '{result['processing_status']}'")
        report("retry_processing הסתיים בהצלחה", result['processing_status'] == 'success')
    except Exception as e:
        report("retry_processing הסתיים בהצלחה", False, str(e))

def test_retry_meters_created():
    """אחרי retry: מונים נוצרו בDB"""
    count = meter_service.count_period_meters(error_period['period_id'])
    print(f"    מונים בDB = {count} (צפוי 10)")
    try:
        assert count == 10
        report("אחרי retry: 10 מונים נוצרו", True)
    except AssertionError as e:
        report("אחרי retry: 10 מונים נוצרו", False, str(e))


#  4. MISSING METER_NUMBER : rows skipped

missing_mn_client = None
missing_mn_period = None
missing_mn_source_file = None
MISSING_MN_FILE = os.path.join(TEST_DIR, "test_data", "missing_meter_number_temp.xlsx")

def create_missing_meter_number_file():
    """Create a file with 10 rows, 1 missing meter_number"""
    import openpyxl
    from datetime import datetime
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["מס'ד", "מס' זיהוי", "מספר מונה", "מספר משדר","נוכחית", "כתובת", "סדר הליכה ","מודל", "קוטר", "תאריך התקנה", "קו אורך", "קו רוחב"])
    # 9 normal rows
    for i in range(1, 10):
        ws.append([i, 10000 + i, f"METER{i:03d}", f"METER{i:03d}", 100.0 + i,
                   f"רחוב {i}", 1000 + i, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    # 1 row with missing meter_number
    ws.append([10, 10010, None, None, 110.0,"רחוב 10", 1010, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    wb.save(MISSING_MN_FILE)

def setup_missing_meter_number():
    global missing_mn_client, missing_mn_period, missing_mn_source_file
    create_missing_meter_number_file()
    missing_mn_client = client_service.create_client("תאגיד מונה חסר", "800000010")
    missing_mn_period = period_service.create_period(missing_mn_client['client_id'], 2026, 1)
    missing_mn_source_file = source_file_service.upload_period_file( period_id=missing_mn_period['period_id'],
        original_filename="missing_meter_number.xlsx", file_type="netanya_format",
        uploaded_by="test_script", file_path=MISSING_MN_FILE)
    print(f"  נוצר קובץ עם 10 שורות, 1 בלי מספר מונה")

def test_skipped_row_still_succeeds():
    """שורה בלי meter_number נדלגת, עיבוד מצליח"""
    try:
        result = source_file_service.process_uploaded_file(missing_mn_source_file['source_file_id'])
        # 1 out of 10 = 10%, but let's check what status we get
        report(f"עיבוד עם שורה חסרה הצליח (status: {result['processing_status']})", 
               result['processing_status'] in ('success', 'partial'))
    except Exception as e:
        report("עיבוד עם שורה חסרה", False, str(e))

def test_skipped_row_count():
    """9 מונים נוצרו (שורה אחת נדלגה)"""
    count = meter_service.count_period_meters(missing_mn_period['period_id'])
    print(f"    מונים בDB = {count} (צפוי 9)")
    try:
        assert count == 9
        report("9 מונים נוצרו (1 נדלגה)", True)
    except AssertionError as e:
        report("9 מונים נוצרו (1 נדלגה)", False, str(e))

def test_skipped_row_error_message():
    """הודעה על שורה שנדלגה נשמרת"""
    sf = source_file_service.get_source_file(missing_mn_source_file['source_file_id'])
    print(f"    error_message = '{sf['error_message'][:100]}...'")
    try:
        assert sf['error_message'] is not None and "נדלגו" in sf['error_message']
        report("הודעה על שורה שנדלגה נשמרת", True)
    except AssertionError as e:
        report("הודעה על שורה שנדלגה נשמרת", False, str(e))

#  5. MISSING OPTIONAL FIELDS : meters with missing_info

missing_fields_client = None
missing_fields_period = None
missing_fields_source_file = None
MISSING_FIELDS_FILE = os.path.join(TEST_DIR, "test_data", "missing_fields_temp.xlsx")

def create_missing_fields_file():
    """Create a file with 10 rows, 2 missing address"""
    import openpyxl
    from datetime import datetime
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["מס'ד", "מס' זיהוי", "מספר מונה", "מספר משדר", "נוכחית", "כתובת", "סדר הליכה ", "מודל", "קוטר", "תאריך התקנה", "קו אורך", "קו רוחב"])
    # 8 normal rows
    for i in range(1, 9):
        ws.append([i, 20000 + i, f"FMETER{i:03d}", f"FMETER{i:03d}", 200.0 + i,
                   f"כתובת {i}", 2000 + i, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    # 2 rows with meter_number but missing address
    ws.append([9, 20009, "FMETER009", "FMETER009", 209.0, None, 2009, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    ws.append([10, 20010, "FMETER010", "FMETER010", 210.0, None, 2010, "מודל", '0.75"',datetime(2024, 1, 1), 34.87, 32.34])
    wb.save(MISSING_FIELDS_FILE)

def setup_missing_fields():
    global missing_fields_client, missing_fields_period, missing_fields_source_file
    create_missing_fields_file()
    missing_fields_client = client_service.create_client("תאגיד שדות חסרים", "800000020")
    missing_fields_period = period_service.create_period(missing_fields_client['client_id'], 2026, 1)
    missing_fields_source_file = source_file_service.upload_period_file( period_id=missing_fields_period['period_id'],
        original_filename="missing_fields.xlsx",  file_type="netanya_format",
        uploaded_by="test_script", file_path=MISSING_FIELDS_FILE)
    print(f"  נוצר קובץ עם 10 שורות, 2 בלי כתובת")

def test_missing_fields_all_imported():
    """כל 10 השורות יובאו (יש meter_number לכולן)"""
    source_file_service.process_uploaded_file(missing_fields_source_file['source_file_id'])
    count = meter_service.count_period_meters(missing_fields_period['period_id'])
    print(f"    מונים בDB = {count} (צפוי 10)")
    try:
        assert count == 10
        report("כל 10 המונים יובאו", True)
    except AssertionError as e:
        report("כל 10 המונים יובאו", False, str(e))

def test_missing_fields_status_is_missing_info():
    """מונים עם כתובת חסרה מסומנים missing_info"""
    meter = meter_service.get_meter_by_number(missing_fields_period['period_id'], "FMETER009")
    if not meter:
        report("מונה עם שדה חסר", False, "לא נמצא")
        return
    print(f"    FMETER009 work_status = '{meter['work_status']}'")
    try:
        assert meter['work_status'] == 'missing_info'
        report("מונה עם כתובת חסרה → work_status='missing_info'", True)
    except AssertionError as e:
        report("מונה עם כתובת חסרה → work_status='missing_info'", False, str(e))

def test_missing_fields_in_raw_data():
    """missing_fields מופיע ב-raw_data"""
    meter = meter_service.get_meter_by_number(missing_fields_period['period_id'], "FMETER009")
    if not meter:
        report("raw_data.missing_fields", False, "מונה לא נמצא")
        return
    raw = meter.get('raw_data', {})
    print(f"    raw_data = {raw}")
    try:
        assert 'missing_fields' in raw and 'address' in raw['missing_fields']
        report("raw_data.missing_fields כולל 'address'", True)
    except AssertionError as e:
        report("raw_data.missing_fields כולל 'address'", False, str(e))

def test_normal_meters_still_new():
    """מונים תקינים נשארים בסטטוס new"""
    meter = meter_service.get_meter_by_number(missing_fields_period['period_id'], "FMETER001")
    if not meter:
        report("מונה תקין", False, "לא נמצא")
        return
    print(f"    FMETER001 work_status = '{meter['work_status']}'")
    try:
        assert meter['work_status'] == 'new'
        report("מונה תקין → work_status='new'", True)
    except AssertionError as e:
        report("מונה תקין → work_status='new'", False, str(e))

def test_missing_fields_file_status_success():
    """סטטוס קובץ success (אין שורות שנדלגו)"""
    sf = source_file_service.get_source_file(missing_fields_source_file['source_file_id'])
    print(f"    processing_status = '{sf['processing_status']}'")
    try:
        assert sf['processing_status'] == 'success'
        report("סטטוס קובץ success (שדות חסרים לא גורמים לדילוג)", True)
    except AssertionError as e:
        report("סטטוס קובץ success (שדות חסרים לא גורמים לדילוג)", False, str(e))

#  6. PARTIAL STATUS : >5% skipped rows

partial_client = None
partial_period = None
partial_source_file = None
PARTIAL_FILE = os.path.join(TEST_DIR, "test_data", "partial_temp.xlsx")


def create_partial_file():
    """Create a file with 20 rows, 3 missing meter_number (15% > 5%)"""
    import openpyxl
    from datetime import datetime
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["מס'ד", "מס' זיהוי", "מספר מונה", "מספר משדר",
               "נוכחית", "כתובת", "סדר הליכה ", "מודל", "קוטר", "תאריך התקנה", "קו אורך", "קו רוחב"])
    # 17 normal rows
    for i in range(1, 18):
        ws.append([i, 30000 + i, f"PMETER{i:03d}", f"PMETER{i:03d}", 300.0 + i, f"כתובת {i}", 3000 + i, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    # 3 rows missing meter_number (15%)
    for i in range(18, 21):
        ws.append([i, 30000 + i, None, None, 300.0 + i,  f"כתובת {i}", 3000 + i, "מודל", '0.75"',datetime(2024, 1, 1), 34.87, 32.34])
    wb.save(PARTIAL_FILE)

def setup_partial():
    global partial_client, partial_period, partial_source_file
    create_partial_file()
    partial_client = client_service.create_client("תאגיד חלקי", "800000030")
    partial_period = period_service.create_period(partial_client['client_id'], 2026, 1)
    partial_source_file = source_file_service.upload_period_file( period_id=partial_period['period_id'],
        original_filename="partial.xlsx", file_type="netanya_format",  uploaded_by="test_script", file_path=PARTIAL_FILE )
    print(f"  נוצר קובץ עם 20 שורות, 3 בלי מספר מונה (15%)")

def test_partial_status():
    """יותר מ-5% שורות חסרות → processing_status='partial'"""
    source_file_service.process_uploaded_file(partial_source_file['source_file_id'])
    sf = source_file_service.get_source_file(partial_source_file['source_file_id'])
    print(f"    processing_status = '{sf['processing_status']}'")
    try:
        assert sf['processing_status'] == 'partial'
        report("מעל 5% שורות חסרות → status='partial'", True)
    except AssertionError as e:
        report("מעל 5% שורות חסרות → status='partial'", False, str(e))

def test_partial_rows_count():
    """17 מונים נוצרו מתוך 20"""
    count = meter_service.count_period_meters(partial_period['period_id'])
    print(f"    מונים בDB = {count} (צפוי 17)")
    try:
        assert count == 17
        report("17 מונים נוצרו (3 נדלגו)", True)
    except AssertionError as e:
        report("17 מונים נוצרו (3 נדלגו)", False, str(e))

def test_partial_error_message():
    """הודעה מפורטת על שורות שנדלגו"""
    sf = source_file_service.get_source_file(partial_source_file['source_file_id'])
    print(f"    error_message = '{sf['error_message'][:100]}...'")
    try:
        assert sf['error_message'] is not None and "17 מתוך 20" in sf['error_message']
        report("הודעה מציינת 17 מתוך 20", True)
    except AssertionError as e:
        report("הודעה מציינת 17 מתוך 20", False, str(e))

def cleanup_temp_files():
    """מוחק את כל קבצי ה-Excel הזמניים שנוצרו לצורך הבדיקות"""
    for path in [MISSING_MN_FILE, MISSING_FIELDS_FILE, PARTIAL_FILE]:
        if os.path.exists(path):
            os.remove(path)

#  RUN ALL TESTS : 

def main():
    print("=" * 60)
    print("  Monim : process_uploaded_file Integration Test")
    print("=" * 60)

    try:
        # 1. Happy path
        print("\n=== הכנה: happy path ===")
        setup_happy_path()

        print("\n=== בדיקות עיבוד תקין ===")
        test_process_uploaded_file_succeeds()
        test_source_file_status_success()
        test_source_file_rows_count()
        test_period_status_active()
        test_meters_created()
        test_meter_data_correct()
        test_all_meters_status_new()          # ← חדש
        test_happy_path_status_summary() 
        test_null_walk_order_meter()          # ← חדש
        test_int_meter_number_stored_as_string()  # ← חדש

        # 2. Error handling
        print("\n=== הכנה: error path ===")
        setup_error_path()

        print("\n=== בדיקות טיפול בשגיאות ===")
        test_process_bad_file_marks_error()
        test_error_message_saved()
        test_no_partial_meters_after_error()

        # 3. Retry
        print("\n=== בדיקות retry ===")
        test_retry_processing_succeeds()
        test_retry_meters_created()

        # 4. Missing meter_number
        print("\n=== הכנה: שורה בלי מספר מונה ===")
        setup_missing_meter_number()

        print("\n=== בדיקות דילוג על שורות ===")
        test_skipped_row_still_succeeds()
        test_skipped_row_count()
        test_skipped_row_error_message()

        # 5. Missing optional fields
        print("\n=== הכנה: שדות אופציונליים חסרים ===")
        setup_missing_fields()

        print("\n=== בדיקות missing_info ===")
        test_missing_fields_all_imported()
        test_missing_fields_status_is_missing_info()
        test_missing_fields_in_raw_data()
        test_normal_meters_still_new()
        test_missing_fields_file_status_success()

        # 6. Partial status
        print("\n=== הכנה: סטטוס partial ===")
        setup_partial()

        print("\n=== בדיקות partial ===")
        test_partial_status()
        test_partial_rows_count()
        test_partial_error_message()

        # Summary
        print("\n" + "=" * 60)
        print_summary()
        print("=" * 60)

    finally:
        cleanup_temp_files()
        cleanup()


if __name__ == "__main__":
    main()