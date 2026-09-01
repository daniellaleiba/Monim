"""
Monim - Reading Error Tests
Testing edge cases, validation, and error handling for Reading entity.

Tests Summary:

1. Validation Errors (3 tests)
   - Reading on non-existent meter (blocked)
   - Reading with None value (blocked)
   - Negative reading value (allowed - indicates meter issue)

2. Reading Creation and Calculation (4 tests)
   - Valid reading with correct consumption calculation
   - Reading lower than previous (negative consumption - allowed)
   - Consumption calculated correctly
   - Previous reading snapshot saved from period_meter

3. State Updates After Reading (3 tests)
   - Meter work_status updates to in_progress
   - Folder status updates to in_progress on first reading
   - Multiple readings on same meter (history preserved, content verified)

4. Status Management (6 tests)
   - Approve reading - meter becomes completed
   - Approve already approved reading (blocked)
   - Reject reading - meter stays in_progress
   - Request recheck - meter stays in_progress
   - Reject reading not in reviewable status (blocked)
   - requires_review flow: flag + appears in review list + approve; flag + reject

5. Folder Completion (3 tests)
   - Folder completed_meters increments after approval
   - Re-approving an already-completed meter does not double-count
     (regression test for a real off-by-one bug found and fixed in ReadingService.complete_meter_reading during this test review)
   - Folder auto-completes when all meters done

6. Not Found / Delete (3 tests)
   - Get non-existent reading
   - Approve non-existent reading (blocked)
   - Delete reading: succeeds for real, blocked for non-existent

Total: 22 tests
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.test_helpers import report, print_summary, cleanup, reset_counters
from src.services.client_service import ClientService
from src.services.reader_service import ReaderService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.workfolder_service import WorkFolderService
from src.services.reading_service import ReadingService

client_service = ClientService()
reader_service = ReaderService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
reading_service = ReadingService()

# Shared test data
test_client = None
test_period = None
test_folder = None
test_reader = None
test_meters = None


def setup():
    """Create full test environment: client, period, file, meters, folder, reader"""
    global test_client, test_period, test_folder, test_reader, test_meters

    # Client
    test_client = client_service.create_client("עיריית קריאות בדיקה", "100000040")

    # Periods
    periods = period_service.initialize_periods_for_year(test_client['client_id'], 2026)
    test_period = periods[0]

    # Source file
    sf = source_file_service.upload_period_file( period_id=test_period['period_id'],
        original_filename="test_readings.xlsx", file_type="excel")

    # Create 5 meters
    rows = []
    for i in range(1, 6):
        rows.append({'row_number': i, 'meter_number': f'MTR-READ-{i:04d}',
            'customer_number': f'CUST-{i:03d}', 'customer_name': f'לקוח קריאה {i}',
            'address': f'רחוב קריאה {i}', 'walk_order': 1000 + (i * 100),
            'previous_reading': 100.0 * i, 'installation_date': '2020-01-01','raw_data': {'test': i}})
    meter_service.create_meters_from_parsed_rows(test_period['period_id'], sf['source_file_id'], rows)

    # Template + folder
    template_service.create_template(test_client['client_id'], 1, "תיק קריאות", 1000, 2000)
    folder_service.create_folders_for_period(test_period['period_id'])
    folder_service.distribute_meters_into_folders(test_period['period_id'])

    # Assign reader
    test_reader = reader_service.create_reader( name="קורא לשיוך", username="assign_test", password_hash="hash123")
    folders = folder_service.get_period_folders(test_period['period_id'])
    test_folder = folders[0]
    folder_service.assign_reader_to_folder(test_folder['folder_id'], test_reader['reader_id'])

    # Get meters
    test_meters = meter_service.get_period_meters(test_period['period_id'])

    print(f"  Setup: לקוח, תקופה, 5 מונים, תיק עם קורא {test_reader['name']}")

#  1. VALIDATION ERRORS

def test_reading_nonexistent_meter():
    """קריאה על מונה שלא קיים"""
    try:
        reading_service.create_reading(period_meter_id=99999, reader_id=test_reader['reader_id'],current_reading=500 )
        report("קריאה על מונה לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("קריאה על מונה לא קיים (חסום)", True)
        except AssertionError as ae:
            report("קריאה על מונה לא קיים (חסום)", False, str(ae))

def test_reading_none_value():
    """קריאה עם ערך None"""
    try:
        reading_service.create_reading( period_meter_id=test_meters[0]['period_meter_id'],reader_id=test_reader['reader_id'], current_reading=None)
        report("קריאה עם ערך None", False, "לא נזרקה שגיאה")
    except ValueError:
        report("קריאה עם ערך None (חסום)", True)

def test_reading_negative_value_allowed():
    """קריאה עם ערך שלילי - מותר, מעיד על בעיה במונה"""
    try:
        reading = reading_service.create_reading( period_meter_id=test_meters[4]['period_meter_id'], reader_id=test_reader['reader_id'], 
            current_reading=-5, fault_code="negative_reading", notes="קריאה שלילית - בעיה במונה")
        assert reading is not None
        assert reading['current_reading'] == -5
        report("קריאה שלילית (מותר - בעיה במונה)", True)
    except AssertionError as e:
        report("קריאה שלילית (מותר - בעיה במונה)", False, str(e))

#  2. READING CREATION AND CALCULATION

def test_valid_reading_with_consumption():
    """קריאה תקינה עם חישוב צריכה"""
    try:
        meter = test_meters[0]
        reading = reading_service.create_reading( period_meter_id=meter['period_meter_id'], reader_id=test_reader['reader_id'], current_reading=250.5)

        assert reading is not None
        assert reading['current_reading'] == 250.5
        assert reading['previous_reading'] == meter['previous_reading']
        assert float(reading['consumption']) == 250.5 - float(meter['previous_reading'])
        report("קריאה תקינה + צריכה מחושבת", True)
    except AssertionError as e:
        report("קריאה תקינה + צריכה מחושבת", False, str(e))

def test_reading_lower_than_previous():
    """קריאה נמוכה מהקודמת - צריכה שלילית, מותר"""
    try:
        meter = test_meters[1]
        reading = reading_service.create_reading( period_meter_id=meter['period_meter_id'],
                reader_id=test_reader['reader_id'], current_reading=150.0, notes="קריאה נמוכה מקודמת - ייתכן החלפת מונה")

        assert reading is not None
        assert float(reading['consumption']) < 0
        report("קריאה נמוכה מקודמת - צריכה שלילית (מותר)", True)
    except AssertionError as e:
        report("קריאה נמוכה מקודמת - צריכה שלילית (מותר)", False, str(e))

def test_previous_reading_snapshot():
    """previous_reading בקריאה נשמר כ-snapshot מהמונה"""
    try:
        meter = test_meters[2]
        reading = reading_service.create_reading( period_meter_id=meter['period_meter_id'],
            reader_id=test_reader['reader_id'], current_reading=500.0)

        assert reading['previous_reading'] == meter['previous_reading']
        report("snapshot של previous_reading מהמונה", True)
    except AssertionError as e:
        report("snapshot של previous_reading מהמונה", False, str(e))

def test_consumption_calculation():
    """חישוב צריכה: current - previous"""
    try:
        meter = test_meters[3]
        reading = reading_service.create_reading(period_meter_id=meter['period_meter_id'],
            reader_id=test_reader['reader_id'], current_reading=650.0)

        expected_consumption = 650.0 - float(meter['previous_reading'])
        assert float(reading['consumption']) == expected_consumption
        report(f"חישוב צריכה: 650-{float(meter['previous_reading'])}={expected_consumption}", True)
    except AssertionError as e:
        report(f"חישוב צריכה", False, str(e))

#  3. STATE UPDATES AFTER READING

def test_meter_status_updates_to_in_progress():
    """סטטוס מונה מתעדכן ל-in_progress אחרי קריאה"""
    try:
        meter = test_meters[0]
        updated = meter_service.get_meter(meter['period_meter_id'])
        assert updated['work_status'] == 'in_progress'
        report("סטטוס מונה -> in_progress אחרי קריאה", True)
    except AssertionError as e:
        report("סטטוס מונה -> in_progress אחרי קריאה", False, str(e))

def test_folder_status_updates_to_in_progress():
    """סטטוס תיק מתעדכן ל-in_progress אחרי קריאה ראשונה"""
    try:
        updated_folder = folder_service.get_folder(test_folder['folder_id'])
        assert updated_folder['status'] == 'in_progress'
        report("סטטוס תיק -> in_progress אחרי קריאה ראשונה", True)
    except AssertionError as e:
        report("סטטוס תיק -> in_progress אחרי קריאה ראשונה", False, str(e))

def test_multiple_readings_on_same_meter():
    """כמה קריאות על אותו מונה - היסטוריה נשמרת, לא נדרסת"""
    try:
        meter = test_meters[0]
        reading1_before = reading_service.get_meter_readings(meter['period_meter_id'])
        count_before = len(reading1_before)

        reading2 = reading_service.create_reading( period_meter_id=meter['period_meter_id'],
            reader_id=test_reader['reader_id'], current_reading=300.0, notes="קריאה שנייה - תיקון")

        all_readings = reading_service.get_meter_readings(meter['period_meter_id'])
        assert len(all_readings) == count_before + 1  # נוספה בדיוק אחת, לא נדרסה

        # הקריאה החדשה עצמה נכתבה נכון
        assert reading2['current_reading'] == 300.0
        assert reading2['notes'] == "קריאה שנייה - תיקון"

        # הקריאה החדשה אכן מופיעה בהיסטוריה, לא רק ב-return value
        assert any(r['reading_id'] == reading2['reading_id'] for r in all_readings)

        report("כמה קריאות על אותו מונה - היסטוריה נשמרת (לא נדרסת)", True)
    except AssertionError as e:
        report("כמה קריאות על אותו מונה - היסטוריה נשמרת (לא נדרסת)", False, str(e))

#  4. STATUS MANAGEMENT

def test_approve_reading():
    """אישור קריאה - מונה הופך ל-completed"""
    try:
        meter = test_meters[1]
        readings = reading_service.get_meter_readings(meter['period_meter_id'])
        reading = readings[0]

        reading_service.approve_reading(reading['reading_id'])

        approved = reading_service.get_reading(reading['reading_id'])
        assert approved['reading_status'] == 'approved'

        updated_meter = meter_service.get_meter(meter['period_meter_id'])
        assert updated_meter['work_status'] == 'completed'
        report("אישור קריאה - מונה completed", True)
    except AssertionError as e:
        report("אישור קריאה - מונה completed", False, str(e))

def test_approve_already_approved():
    """אישור קריאה שכבר אושרה - צריך להיחסם"""
    meter = test_meters[1]
    readings = reading_service.get_meter_readings(meter['period_meter_id'])
    reading = readings[0]

    try:
        reading_service.approve_reading(reading['reading_id'])
        report("אישור קריאה שכבר אושרה", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "submitted" in str(e) or "requires_review" in str(e)
            report("אישור קריאה שכבר אושרה (חסום)", True)
        except AssertionError as ae:
            report("אישור קריאה שכבר אושרה (חסום)", False, str(ae))

def test_reject_reading():
    """דחיית קריאה - מונה נשאר in_progress"""
    try:
        meter = test_meters[2]
        readings = reading_service.get_meter_readings(meter['period_meter_id'])
        reading = readings[0]

        reading_service.reject_reading(reading['reading_id'])

        rejected = reading_service.get_reading(reading['reading_id'])
        assert rejected['reading_status'] == 'rejected'

        updated_meter = meter_service.get_meter(meter['period_meter_id'])
        assert updated_meter['work_status'] == 'in_progress'
        report("דחיית קריאה - מונה נשאר in_progress", True)
    except AssertionError as e:
        report("דחיית קריאה - מונה נשאר in_progress", False, str(e))

def test_request_recheck():
    """בקשת קריאה חוזרת"""
    try:
        meter = test_meters[3]
        readings = reading_service.get_meter_readings(meter['period_meter_id'])
        reading = readings[0]

        reading_service.request_recheck(reading['reading_id'])

        rechecked = reading_service.get_reading(reading['reading_id'])
        assert rechecked['reading_status'] == 'recheck'

        updated_meter = meter_service.get_meter(meter['period_meter_id'])
        assert updated_meter['work_status'] == 'in_progress'
        report("בקשת קריאה חוזרת - recheck", True)
    except AssertionError as e:
        report("בקשת קריאה חוזרת - recheck", False, str(e))

def test_reject_non_reviewable():
    """דחיית קריאה שכבר נדחתה - צריך להיחסם"""
    meter = test_meters[2]
    readings = reading_service.get_meter_readings(meter['period_meter_id'])
    reading = readings[0]  # Already rejected

    try:
        reading_service.reject_reading(reading['reading_id'])
        report("דחייה כפולה", False, "לא נזרקה שגיאה")
    except ValueError:
        report("דחייה כפולה (חסום)", True)

def test_mark_requires_review_flow():
    """מסלול requires_review מלא: סימון + אישור, וסימון + דחייה"""
    meter_a = test_meters[4]
    readings_a = reading_service.get_meter_readings(meter_a['period_meter_id'])
    reading_a = readings_a[0]

    try:
        reading_service.mark_requires_review(reading_a['reading_id'])
        flagged = reading_service.get_reading(reading_a['reading_id'])
        assert flagged['reading_status'] == 'requires_review'
        in_review_list = reading_service.get_readings_for_review()
        assert any(r['reading_id'] == reading_a['reading_id'] for r in in_review_list)
        reading_service.approve_reading(reading_a['reading_id'])
        approved = reading_service.get_reading(reading_a['reading_id'])
        assert approved['reading_status'] == 'approved'
        report("requires_review -> approve (+ מופיע ברשימת הבדיקה)", True)
    except AssertionError as e:
        report("requires_review -> approve (+ מופיע ברשימת הבדיקה)", False, str(e))

    try:
        meter_b = test_meters[2]  # מונה אחר לגמרי - לא אותו מונה
        reading_b = reading_service.create_reading(
            period_meter_id=meter_b['period_meter_id'], reader_id=test_reader['reader_id'], current_reading=1234.0)
        reading_service.mark_requires_review(reading_b['reading_id'])
        reading_service.reject_reading(reading_b['reading_id'])
        rejected = reading_service.get_reading(reading_b['reading_id'])
        assert rejected['reading_status'] == 'rejected'
        report("requires_review -> reject", True)
    except AssertionError as e:
        report("requires_review -> reject", False, str(e))

#  5. FOLDER COMPLETION

def test_folder_completion_increments():
    """ספירת completed_meters בתיק עולה בדיוק ב-1 אחרי אישור"""
    try:
        before = folder_service.get_folder(test_folder['folder_id'])
        count_before = before['completed_meters']

        meter = test_meters[0]
        reading = reading_service.create_reading(
            period_meter_id=meter['period_meter_id'], reader_id=test_reader['reader_id'], current_reading=888.0)
        reading_service.approve_reading(reading['reading_id'])

        after = folder_service.get_folder(test_folder['folder_id'])
        assert after['completed_meters'] == count_before + 1
        report("completed_meters בתיק עולה בדיוק ב-1 אחרי אישור", True)
    except AssertionError as e:
        report("completed_meters בתיק עולה בדיוק ב-1 אחרי אישור", False, str(e))

def test_double_completion_does_not_double_count():
    """אישור נוסף על מונה שכבר completed - לא סופר פעם שנייה"""
    try:
        meter = test_meters[1]  # כבר completed מ-test_approve_reading
        before = folder_service.get_folder(test_folder['folder_id'])
        count_before = before['completed_meters']

        reading = reading_service.create_reading(
            period_meter_id=meter['period_meter_id'], reader_id=test_reader['reader_id'], current_reading=1600.0)
        reading_service.approve_reading(reading['reading_id'])

        after = folder_service.get_folder(test_folder['folder_id'])
        assert after['completed_meters'] == count_before  # לא עלה בכלל - כבר נספר בעבר
        report("אישור על מונה שכבר completed - לא נספר שוב", True)
    except AssertionError as e:
        report("אישור על מונה שכבר completed - לא נספר שוב", False, str(e))

def test_folder_auto_completes():
    """תיק מסתיים אוטומטית כשכל המונים הושלמו"""
    try:
        folder_meters = meter_service.get_folder_meters(test_folder['folder_id'])
        for m in folder_meters:
            if m['work_status'] != 'completed':
                reading = reading_service.create_reading( period_meter_id=m['period_meter_id'], reader_id=test_reader['reader_id'], current_reading=999.0)
                reading_service.approve_reading(reading['reading_id'])

        updated_folder = folder_service.get_folder(test_folder['folder_id'])
        assert updated_folder['status'] == 'completed'
        assert updated_folder['completed_at'] is not None
        report("תיק הושלם אוטומטית כשכל המונים completed", True)
    except AssertionError as e:
        report("תיק הושלם אוטומטית כשכל המונים completed", False, str(e))

#  6. NOT FOUND, Delete

def test_get_nonexistent_reading():
    """שליפת קריאה שלא קיימת"""
    try:
        result = reading_service.get_reading(99999)
        assert result is None
        report("שליפת קריאה לא קיימת", True)
    except AssertionError as e:
        report("שליפת קריאה לא קיימת", False, str(e))

def test_approve_nonexistent_reading():
    """אישור קריאה שלא קיימת"""
    try:
        reading_service.approve_reading(99999)
        report("אישור קריאה לא קיימת", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצאה" in str(e)
            report("אישור קריאה לא קיימת (חסום)", True)
        except AssertionError as ae:
            report("אישור קריאה לא קיימת (חסום)", False, str(ae))

def test_delete_reading():
    """מחיקת קריאה - מצליחה בפועל, וחסומה על קריאה לא קיימת"""
    try:
        meter = test_meters[0]
        reading = reading_service.create_reading(
            period_meter_id=meter['period_meter_id'], reader_id=test_reader['reader_id'], current_reading=777.0)

        result = reading_service.delete_reading(reading['reading_id'])
        assert result is True

        fetched = reading_service.get_reading(reading['reading_id'])
        assert fetched is None
        report("מחיקת קריאה - מוחקת בפועל", True)
    except AssertionError as e:
        report("מחיקת קריאה - מוחקת בפועל", False, str(e))

    try:
        reading_service.delete_reading(99999)
        report("מחיקת קריאה לא קיימת (חסום)", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצאה" in str(e)
            report("מחיקת קריאה לא קיימת (חסום)", True)
        except AssertionError as ae:
            report("מחיקת קריאה לא קיימת (חסום)", False, str(ae))

#  RUN ALL TESTS

def main():
    reset_counters()

    try:
        print("=" * 50)
        print("  Monim tests - Reading Error Tests")
        print("=" * 50)

        # Setup
        print("\n=== הכנה ===")
        setup()

        # 1. Validation
        print("\n=== בדיקות ולידציה ===")
        test_reading_nonexistent_meter()
        test_reading_none_value()
        test_reading_negative_value_allowed()

        # 2. Creation and calculation
        print("\n=== בדיקות יצירה וחישוב ===")
        test_valid_reading_with_consumption()
        test_reading_lower_than_previous()
        test_previous_reading_snapshot()
        test_consumption_calculation()

        # 3. State updates
        print("\n=== בדיקות עדכון מצב ===")
        test_meter_status_updates_to_in_progress()
        test_folder_status_updates_to_in_progress()
        test_multiple_readings_on_same_meter()

        # 4. Status management
        print("\n=== בדיקות ניהול סטטוס ===")
        test_approve_reading()
        test_approve_already_approved()
        test_reject_reading()
        test_request_recheck()
        test_reject_non_reviewable()
        test_mark_requires_review_flow()

        # 5. Folder completion
        print("\n=== בדיקות השלמת תיק ===")
        test_folder_completion_increments()
        test_double_completion_does_not_double_count()
        test_folder_auto_completes()

        # 6. Not found and delete
        print("\n=== בדיקות רשומה לא קיימת ===")
        test_get_nonexistent_reading()
        test_approve_nonexistent_reading()
        test_delete_reading()

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        cleanup()


if __name__ == "__main__":
    main()