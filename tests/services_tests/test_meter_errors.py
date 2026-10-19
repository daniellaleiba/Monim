"""
Monim  - Period Meter Error Tests
Testing edge cases, validation, and error handling for PeriodMeter entity.

Tests Summary:

1. Validation Errors (3 tests)
   - Missing meter_number in parsed rows
   - Missing row_number in parsed rows
   - Empty rows list

2. Source File Validation (2 tests)
   - Create meters with non-existent source file
   - Create meters with source file from different period

3. Uniqueness (2 tests)
   - Duplicate meter_number in same period (DB blocks)
   - Same meter_number in different periods (allowed)

4. Counts and Verification (3 tests)
   - Count matches expected after creation
   - Status summary correct after creation
   - Unassigned count matches total before folder assignment

5. Folder Assignment (4 tests)
   - Assign meter to folder updates work_status to assigned
   - Unassign meter resets work_status to new
   - Assign multiple meters at once
   - Assign to non-existent meter (blocked)

6. Work Status (5 tests)
   - Update to invalid status (blocked)
   - Mark exception updates both status and fault code
   - Manager notes update
   - Test bulk estimate & calculate_estimate (7 cases)
   - Manager notes: save trimmed, clear with empty / whitespace / None

7. Not Found (4 tests)
   - Get non-existent meter
   - Update status on non-existent meter
   - Delete meters for non-existent source file
   - Update manager notes on non-existent meter

NOTE:
These tests currently share setup data and some depend on previous test state.
They are designed as ordered integration-style checks, not isolated unit tests.

Total: 31 tests
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.test_helpers import report, print_summary, cleanup, reset_counters
from src.services.client_service import ClientService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.workfolder_service import WorkFolderService

client_service = ClientService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()

# Shared test data
test_client = None
test_period = None
test_source_file = None


def setup():
    """Create shared test data: client, period, source file, and some meters"""
    global test_client, test_period, test_source_file

    test_client = client_service.create_client("עיריית מונים בדיקה", "100000020")
    periods = period_service.initialize_periods_for_year(test_client['client_id'], 2026)
    test_period = periods[0]

    test_source_file = source_file_service.upload_period_file(period_id=test_period['period_id'], original_filename="test_meters.xlsx",
        file_type="excel", uploaded_by="מנהל בדיקה")
    print(f"  Setup: לקוח (ID: {test_client['client_id']}), תקופה 1, קובץ מקור")


def create_sample_rows(count=5, start_from=1):
    """Helper: create sample parsed rows"""
    rows = []
    for i in range(start_from, start_from + count):
        rows.append({'row_number': i,'meter_number': f'MTR-TEST-{i:04d}',
            'customer_number': f'CUST-{i:03d}', 'customer_name': f'לקוח בדיקה {i}','address': f'רחוב בדיקה {i}',
            'walk_order': 1000 + (i * 100),'previous_reading': 50.0 * i, 'installation_date': '2020-01-01',
            'raw_data': {'test_row': i}})
    return rows

#  1. VALIDATION ERRORS - bad parsed rows

def test_create_missing_meter_number():
    """שורה בלי meter_number - צריך להיכשל"""
    rows = [{'row_number': 1, 'customer_name': 'לקוח בלי מונה'}]
    try:
        meter_service.create_meters_from_parsed_rows(test_period['period_id'], test_source_file['source_file_id'], rows)
        report("שורה בלי meter_number", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "מספר מונה חסר" in str(e)
            report("שורה בלי meter_number", True)
        except AssertionError as ae:
            report("שורה בלי meter_number", False, str(ae))

def test_create_missing_row_number():
    """שורה בלי row_number - צריך להיכשל"""
    rows = [{'meter_number': 'MTR-BAD-001', 'customer_name': 'לקוח'}]
    try:
        meter_service.create_meters_from_parsed_rows(test_period['period_id'], test_source_file['source_file_id'], rows )
        report("שורה בלי row_number", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "מספר שורה" in str(e)
            report("שורה בלי row_number", True)
        except AssertionError as ae:
            report("שורה בלי row_number", False, str(ae))

def test_create_empty_rows():
    """רשימת שורות ריקה - צריך להיכשל"""
    try:
        meter_service.create_meters_from_parsed_rows(test_period['period_id'], test_source_file['source_file_id'], [])
        report("רשימת שורות ריקה", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "אין שורות" in str(e)
            report("רשימת שורות ריקה", True)
        except AssertionError as ae:
            report("רשימת שורות ריקה", False, str(ae))


#  2. SOURCE FILE VALIDATION

def test_create_with_nonexistent_source_file():
    """יצירת מונים עם קובץ מקור שלא קיים"""
    rows = create_sample_rows(1)
    try:
        meter_service.create_meters_from_parsed_rows( test_period['period_id'], 99999, rows)
        report("קובץ מקור לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("קובץ מקור לא קיים", True)
        except AssertionError as ae:
            report("קובץ מקור לא קיים", False, str(ae))

def test_create_with_wrong_period_source_file():
    """יצירת מונים עם קובץ מקור מתקופה אחרת"""
    # Upload a file to period 2
    period_2 = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)
    sf_2 = source_file_service.upload_period_file( period_id=period_2['period_id'], original_filename="wrong_period.xlsx", file_type="excel")

    rows = create_sample_rows(1)
    try:
        # Try to use period 2's file with period 1
        meter_service.create_meters_from_parsed_rows(test_period['period_id'], sf_2['source_file_id'], rows)
        report("קובץ מקור מתקופה אחרת", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא שייך" in str(e)
            report("קובץ מקור מתקופה אחרת", True)
        except AssertionError as ae:
            report("קובץ מקור מתקופה אחרת", False, str(ae))


#  3. UNIQUENESS : duplicate meters

def test_duplicate_meter_in_same_period():
    """מונה כפול באותה תקופה - ה-DB צריך לחסום"""
    # Create first batch
    rows1 = create_sample_rows(3, start_from=100)
    meter_service.create_meters_from_parsed_rows(
        test_period['period_id'], test_source_file['source_file_id'], rows1)

    # Try to create same meters again
    try:
        meter_service.create_meters_from_parsed_rows( test_period['period_id'], test_source_file['source_file_id'], rows1)
        report("מונה כפול באותה תקופה", False, "לא נזרקה שגיאה")
    except Exception:
        report("מונה כפול באותה תקופה (חסום)", True)

def test_same_meter_different_period_allowed():
    """אותו מספר מונה בתקופה אחרת - צריך להצליח"""
    period_2 = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)
    sf_2 = source_file_service.get_period_source_file(period_2['period_id'])

    # Use same meter numbers as period 1 but in period 2
    rows = create_sample_rows(3, start_from=100)
    try:
        count = meter_service.create_meters_from_parsed_rows( period_2['period_id'], sf_2['source_file_id'], rows)
        assert count == 3
        report("אותו מונה בתקופה אחרת (מותר)", True)
    except AssertionError as e:
        report("אותו מונה בתקופה אחרת (מותר)", False, str(e))

#  4. COUNTS AND VERIFICATION

def test_count_matches_created():
    """ספירת מונים תואמת למה שנוצר"""
    try:
        # We created 3 meters in period 1 (from test_duplicate)
        count = meter_service.count_period_meters(test_period['period_id'])
        assert count == 3
        report("ספירה תואמת ליצירה", True)
    except AssertionError as e:
        report("ספירה תואמת ליצירה", False, str(e))

def test_status_summary_after_creation():
    """סיכום סטטוסים אחרי יצירה - הכל new"""
    try:
        summary = meter_service.get_period_status_summary(test_period['period_id'])
        assert summary['total'] == 3
        assert summary['new'] == 3
        assert summary['assigned_to_folder'] == 0
        assert summary['assigned_to_reader'] == 0
        assert summary['unassigned'] == 3
        report("סיכום סטטוסים תקין אחרי יצירה", True)
    except AssertionError as e:
        report("סיכום סטטוסים תקין אחרי יצירה", False, str(e))

def test_unassigned_count_before_folders():
    """כל המונים לא משויכים לפני חלוקה לתיקים"""
    try:
        unassigned = meter_service.get_unassigned_meters(test_period['period_id'])
        total = meter_service.count_period_meters(test_period['period_id'])
        assert len(unassigned) == total
        report("כל המונים לא משויכים לפני חלוקה", True)
    except AssertionError as e:
        report("כל המונים לא משויכים לפני חלוקה", False, str(e))

#  5. FOLDER ASSIGNMENT

def test_assign_meter_to_folder():
    """שיוך מונה לתיק - סטטוס מתעדכן ל-assigned"""
    try:
        # Create template and folder
        template = template_service.create_template(test_client['client_id'], 1, "תיק בדיקה", 10000, 20000)
        folders = folder_service.create_folders_for_period(test_period['period_id'])
        test_folder = folders[0]

        # Get a meter
        meters = meter_service.get_period_meters(test_period['period_id'])
        test_meter = meters[0]

        # Assign
        meter_service.assign_meter_to_folder(test_meter['period_meter_id'], test_folder['folder_id'])

        # Verify
        updated = meter_service.get_meter(test_meter['period_meter_id'])
        assert updated['folder_id'] == test_folder['folder_id']
        assert updated['work_status'] == 'assigned_to_folder'
        report("שיוך מונה לתיק + סטטוס assigned", True)
    except AssertionError as e:
        report("שיוך מונה לתיק + סטטוס assigned", False, str(e))

def test_assign_multiple_meters():
    """שיוך מונים רבים לתיק - כולל דילוג שקט על מונה מתקופה אחרת"""
    try:
        meters = meter_service.get_period_meters(test_period['period_id'])
        folders = folder_service.get_period_folders(test_period['period_id'])
        test_folder = folders[0]

        meter_ids = [m['period_meter_id'] for m in meters]
        count = meter_service.assign_meters_to_folder(meter_ids, test_folder['folder_id'])
        assert count == len(meter_ids)

        # מונה מתקופה אחרת - צריך לדלג בשקט (לא לזרוק), לא להיספר
        period_2 = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)
        meters_p2 = meter_service.get_period_meters(period_2['period_id'])
        mixed_ids = meter_ids + [meters_p2[0]['period_meter_id']]
        count_mixed = meter_service.assign_meters_to_folder(mixed_ids, test_folder['folder_id'])
        assert count_mixed == len(meter_ids)  # לא כולל את מונה התקופה האחרת

        report("שיוך מונים רבים לתיק (כולל דילוג cross-period)", True)
    except AssertionError as e:
        report("שיוך מונים רבים לתיק (כולל דילוג cross-period)", False, str(e))

def test_assign_nonexistent_meter():
    """שיוך מונה שלא קיים"""
    folders = folder_service.get_period_folders(test_period['period_id'])
    try:
        meter_service.assign_meter_to_folder(99999, folders[0]['folder_id'])
        report("שיוך מונה לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("שיוך מונה לא קיים (חסום)", True)
        except AssertionError as ae:
            report("שיוך מונה לא קיים (חסום)", False, str(ae))

def test_assign_meter_to_folder_wrong_period_blocked():
    """שיוך מונה לתיק מתקופה אחרת - צריך להיחסם"""
    period_2 = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)
    folders = folder_service.get_period_folders(test_period['period_id'])  # תיק מתקופה 1
    meters_p2 = meter_service.get_period_meters(period_2['period_id'])     # מונה מתקופה 2
    try:
        meter_service.assign_meter_to_folder(meters_p2[0]['period_meter_id'], folders[0]['folder_id'])
        report("שיוך cross-period", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא שייך" in str(e)
            report("שיוך cross-period (חסום)", True)
        except AssertionError as ae:
            report("שיוך cross-period (חסום)", False, str(ae))

#  6. WORK STATUS AND CURRENT STATE

def test_update_invalid_work_status():
    """עדכון סטטוס עבודה לא חוקי"""
    meters = meter_service.get_period_meters(test_period['period_id'])
    try:
        meter_service.update_work_status(meters[0]['period_meter_id'], 'invalid_status')
        report("סטטוס עבודה לא חוקי", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא תקין" in str(e)
            report("סטטוס עבודה לא חוקי (חסום)", True)
        except AssertionError as ae:
            report("סטטוס עבודה לא חוקי (חסום)", False, str(ae))

def test_mark_exception():
    """סימון מונה כחריג - מעדכן סטטוס וקוד תקלה"""
    try:
        meters = meter_service.get_period_meters(test_period['period_id'])
        test_meter = meters[0]

        meter_service.mark_exception(test_meter['period_meter_id'], "no_access", "שיח חוסם גישה")

        updated = meter_service.get_meter(test_meter['period_meter_id'])
        assert updated['work_status'] == 'exception'
        assert updated['current_fault_code'] == 'no_access'
        assert updated['manager_notes'] == 'שיח חוסם גישה'
        report("סימון חריג - סטטוס + קוד תקלה + הערות", True)
    except AssertionError as e:
        report("סימון חריג - סטטוס + קוד תקלה + הערות", False, str(e))

def test_update_manager_notes():
    """עדכון הערות מנהל"""
    # TODO: בדיקה זו תתרחב בעתיד, עם בניית אפליקציית השטח, כדי לכסות
    # גם current_reading/consumption/addon דרך apply_reading_to_current_state,
    # כרגע מכסה רק manager_notes.
    try:
        meters = meter_service.get_period_meters(test_period['period_id'])
        test_meter = meters[1]

        meter_service.apply_reading_to_current_state(
            test_meter['period_meter_id'], manager_notes="לבדוק בתקופה הבאה")

        updated = meter_service.get_meter(test_meter['period_meter_id'])
        assert updated['manager_notes'] == "לבדוק בתקופה הבאה"
        report("עדכון הערות מנהל", True)
    except AssertionError as e:
        report("עדכון הערות מנהל", False, str(e))

def test_update_and_clear_manager_notes():
    """הערות מנהל: נשמרות בלי רווחים מיותרים, ומתנקות מטקסט ריק / רווחים / None"""
    try:
        meters = meter_service.get_period_meters(test_period['period_id'])
        meter_id = meters[2]['period_meter_id']

        # Saved, without surrounding spaces
        meter_service.update_manager_notes(meter_id, "  מאחורי השער  ")
        assert meter_service.get_meter(meter_id)['manager_notes'] == "מאחורי השער"

        # Empty text clears the note (NULL, not '')
        meter_service.update_manager_notes(meter_id, "")
        assert meter_service.get_meter(meter_id)['manager_notes'] is None

        # Whitespace only clears too
        meter_service.update_manager_notes(meter_id, "הערה")
        meter_service.update_manager_notes(meter_id, "   ")
        assert meter_service.get_meter(meter_id)['manager_notes'] is None

        # None clears too
        meter_service.update_manager_notes(meter_id, "הערה")
        meter_service.update_manager_notes(meter_id, None)
        assert meter_service.get_meter(meter_id)['manager_notes'] is None

        report("הערות מנהל - שמירה וניקוי", True)
    except AssertionError as e:
        report("הערות מנהל - שמירה וניקוי", False, str(e))

def test_update_fault_code_returns_true():
    """עדכון fault_code מחזיר True (לא None)"""
    try:
        meters = meter_service.get_period_meters(test_period['period_id'])
        result = meter_service.update_fault_code(meters[0]['period_meter_id'], '5')
        assert result is True, f"ציפינו ל-True, קיבלנו {result!r}"
        report("update_fault_code מחזיר True", True)
    except AssertionError as e:
        report("update_fault_code מחזיר True", False, str(e))

def test_calculate_and_bulk_estimate():
    """הערכת קריאה (calculate_estimate) ו-bulk_estimate: תקינות וטיפול במקרי קצה"""
    try:
        rows = [
            # מונה עם נתוני היסטוריה תקינים לחישוב רגיל
            {'row_number': 500, 'meter_number': 'MTR-EST-REG', 'previous_reading': 100.0, 'raw_data': {'hist_readings': [100.0, 10.0, 10.0, 10.0, 10.0, 10.0, 8.0]}},
            # מונה עצור - אותם נתוני היסטוריה, יקבל fault_code='1'
            {'row_number': 501, 'meter_number': 'MTR-EST-STOPPED', 'previous_reading': 100.0, 'raw_data': {'hist_readings': [100.0, 10.0, 10.0, 10.0, 10.0, 10.0, 8.0]}},
            # מונה בלי hist_readings בכלל
            {'row_number': 502, 'meter_number': 'MTR-EST-NOHIST', 'previous_reading': 100.0, 'raw_data': {}},
            # מונה בלי fault_code - לא יתאים ל-bulk_estimate
            {'row_number': 503, 'meter_number': 'MTR-EST-NOFAULT', 'previous_reading': 100.0, 'raw_data': {'hist_readings': [100.0, 10.0, 10.0, 10.0, 10.0, 10.0, 8.0]}},
        ]
        meter_service.create_meters_from_parsed_rows(test_period['period_id'], test_source_file['source_file_id'], rows)
        meters = {m['meter_number']: m for m in meter_service.get_period_meters(test_period['period_id'])
                  if m['meter_number'].startswith('MTR-EST-')}

        reg = meters['MTR-EST-REG']
        stopped = meters['MTR-EST-STOPPED']
        nohist = meters['MTR-EST-NOHIST']
        nofault = meters['MTR-EST-NOFAULT']

        # 1. בלי fault_code בכלל - נכשל
        try:
            meter_service.calculate_estimate(reg['period_meter_id'], None)
            report("הערכה בלי fault_code (חסום)", False, "לא נזרקה שגיאה")
        except ValueError:
            report("הערכה בלי fault_code (חסום)", True)

        # 2. בלי hist_readings תקין - נכשל
        try:
            meter_service.calculate_estimate(nohist['period_meter_id'], '5')
            report("הערכה בלי נתוני ק.6 (חסום)", False, "לא נזרקה שגיאה")
        except ValueError:
            report("הערכה בלי נתוני ק.6 (חסום)", True)

        # 2ב. hist_readings חלקי (פחות מ-7 ערכים, אבל לא ריק)
        partial_rows = [{'row_number': 504, 'meter_number': 'MTR-EST-PARTIAL', 'previous_reading': 100.0,
            'raw_data': {'hist_readings': [100.0, 10.0, 10.0]}}]  # רק 3 ערכים
        meter_service.create_meters_from_parsed_rows(test_period['period_id'], test_source_file['source_file_id'], partial_rows)
        partial_meter = meter_service.get_meter_by_number(test_period['period_id'], 'MTR-EST-PARTIAL')
        try:
            meter_service.calculate_estimate(partial_meter['period_meter_id'], '5')
            report("הערכה עם hist_readings חלקי (חסום)", False, "לא נזרקה שגיאה")
        except ValueError:
            report("הערכה עם hist_readings חלקי (חסום)", True)

        # 2ג. מונה שלא קיים בכלל
        try:
            meter_service.calculate_estimate(99999, '5')
            report("הערכה על מונה לא קיים (חסום)", False, "לא נזרקה שגיאה")
        except ValueError:
            report("הערכה על מונה לא קיים (חסום)", True)

        # 3. מונה רגיל: current_reading = previous + q6_diff, addon=None
        result_reg = meter_service.calculate_estimate(reg['period_meter_id'], '5')
        assert result_reg['current_reading'] == 102.0   # 100 + (10-8)
        assert result_reg['addon'] is None
        assert result_reg['is_stopped_meter'] is False
        report("הערכת מונה רגיל - חישוב נכון", True)

        # 4. מונה עצור (fault_code='1'): current_reading נשאר previous, addon=q6_diff
        result_stopped = meter_service.calculate_estimate(stopped['period_meter_id'], '1')
        assert result_stopped['current_reading'] == 100.0
        assert result_stopped['addon'] == 2.0
        assert result_stopped['is_stopped_meter'] is True
        report("הערכת מונה עצור - חישוב נכון", True)

        # 5. bulk_estimate: מעריך רק מונים מתאימים, מדלג על השאר
        meter_service.update_fault_code(reg['period_meter_id'], '5')
        meter_service.update_fault_code(stopped['period_meter_id'], '1')
        # nofault נשאר בלי fault_code בכוונה

        bulk_result = meter_service.bulk_estimate(test_period['period_id'])
        estimated_ids = [u['period_meter_id'] for u in bulk_result['updates']]
        assert reg['period_meter_id'] in estimated_ids
        assert stopped['period_meter_id'] not in estimated_ids
        assert nofault['period_meter_id'] not in estimated_ids
        report("bulk_estimate מעריך רק מונים מתאימים", True)

        # 6. הרצה חוזרת - מונה שכבר הוערך מדולג (idempotent)
        bulk_result_2 = meter_service.bulk_estimate(test_period['period_id'])
        estimated_ids_2 = [u['period_meter_id'] for u in bulk_result_2['updates']]
        assert reg['period_meter_id'] not in estimated_ids_2
        report("bulk_estimate לא מעריך שוב מונה שכבר הוערך", True)

    except AssertionError as e:
        report("הערכת קריאה (calculate_estimate/bulk_estimate)", False, str(e))

#  7. NOT FOUND

def test_get_nonexistent_meter():
    """שליפת מונה שלא קיים"""
    try:
        result = meter_service.get_meter(99999)
        assert result is None
        report("שליפת מונה לא קיים", True)
    except AssertionError as e:
        report("שליפת מונה לא קיים", False, str(e))

def test_update_status_nonexistent():
    """עדכון סטטוס למונה שלא קיים"""
    try:
        meter_service.update_work_status(99999, 'assigned_to_folder')
        report("עדכון סטטוס למונה לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("עדכון סטטוס למונה לא קיים (חסום)", True)
        except AssertionError as ae:
            report("עדכון סטטוס למונה לא קיים (חסום)", False, str(ae))

def test_update_manager_notes_nonexistent():
    """עדכון הערות מנהל למונה שלא קיים"""
    try:
        meter_service.update_manager_notes(99999, "הערה")
        report("הערות מנהל למונה לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("הערות מנהל למונה לא קיים (חסום)", True)
        except AssertionError as ae:
            report("הערות מנהל למונה לא קיים (חסום)", False, str(ae))

def test_delete_by_nonexistent_source_file():
    """מחיקת מונים לפי קובץ מקור - מחזיר 0 אם אין מה למחוק"""
    try:
        count = meter_service.delete_meters_by_source_file(99999)
        assert count == 0
        report("מחיקת מונים לקובץ לא קיים (0 נמחקו)", True)
    except AssertionError as e:
        report("מחיקת מונים לקובץ לא קיים (0 נמחקו)", False, str(e))

#  RUN ALL TESTS

def main():
    reset_counters()

    print("=" * 50)
    print("  Monim tests: Period Meter Error Tests")
    print("=" * 50)

    try: 
        # Setup
        print("\n=== הכנה ===")
        setup()

        # 1. Validation
        print("\n=== בדיקות ולידציה - שורות לא תקינות ===")
        test_create_missing_meter_number()
        test_create_missing_row_number()
        test_create_empty_rows()

        # 2. Source file validation
        print("\n=== בדיקות קובץ מקור ===")
        test_create_with_nonexistent_source_file()
        test_create_with_wrong_period_source_file()

        # 3. Uniqueness
        print("\n=== בדיקות ייחודיות - כפילויות ===")
        test_duplicate_meter_in_same_period()
        test_same_meter_different_period_allowed()

        # 4. Counts
        print("\n=== בדיקות ספירה ואימות ===")
        test_count_matches_created()
        test_status_summary_after_creation()
        test_unassigned_count_before_folders()

        # 5. Folder assignment
        print("\n=== בדיקות שיוך לתיק ===")
        test_assign_meter_to_folder()
        test_assign_multiple_meters()
        test_assign_nonexistent_meter()
        test_assign_meter_to_folder_wrong_period_blocked()

        # 6. Work status
        print("\n=== בדיקות סטטוס ומצב נוכחי ===")
        test_update_invalid_work_status()
        test_mark_exception()
        test_update_manager_notes()
        test_update_and_clear_manager_notes()
        test_update_fault_code_returns_true()
        test_calculate_and_bulk_estimate()

        # 7. Not found
        print("\n=== בדיקות רשומה לא קיימת ===")
        test_get_nonexistent_meter()
        test_update_status_nonexistent()
        test_update_manager_notes_nonexistent()
        test_delete_by_nonexistent_source_file()

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()


if __name__ == "__main__":
    main()