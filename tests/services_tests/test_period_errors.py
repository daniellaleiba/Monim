"""
Monim - Reading Period Error Tests
Testing edge cases, validation, and error handling for ReadingPeriod entity.

Tests Summary:

1. Validation Errors (6 tests)
   - Invalid year: too old, too far in the future
   - Invalid period number: 0, 7, negative
   - Non-existent client

2. Uniqueness (3 tests)
   - Duplicate period (same client + year + number)
   - Double initialization for same year (should skip existing)
   - Initialization for different year (should succeed)

3. Previous Period Lookup (4 tests)
   - Normal case: previous of period 3 is period 2
   - Year crossing: previous of period 1/2026 is period 6/2025
   - Not found: no previous for period 1/2025 (no 2024 data)
   - Non-existent period ID

4. Status Transitions (7 tests)
   - Invalid: pending → active (must go through file_received)
   - Invalid: pending → completed (must go through active)
   - Invalid: file_received → skipped (too late to skip)
   - Valid full flow: pending → file_received → active → completed
   - Invalid: completed → completed (final state)
   - Valid: pending → skipped
   - update_status_manually bypasses transition validation (direct jump allowed, invalid status blocked, non-existent period blocked)

5. Initialize with start_from_period (2 tests)
   - start_from_period=3: periods 1-2 skipped, 3-6 pending
   - Invalid start_from_period=8

6. Not Found (3 tests)
   - Get non-existent period
   - Mark file_received on non-existent period
   - Delete period: non-existent (blocked), existing clean period (success)

Total: 24 tests
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
 
from src.services.client_service import ClientService
from src.services.reading_period_service import ReadingPeriodService
from tests.test_helpers import report, print_summary, cleanup, reset_counters
 
client_service = ClientService()
period_service = ReadingPeriodService()
 
# Shared test client : created once, used by all tests
test_client = None
 

def setup():
    """Create a shared test client for all period tests"""
    global test_client
    test_client = client_service.create_client("עיריית תקופות בדיקה", "100000001")
    print(f"  Setup: נוצר לקוח בדיקה (ID: {test_client['client_id']})")
 
 
#  1. VALIDATION ERRORS : bad input
 
def test_create_period_invalid_year_too_old():
    """יצירת תקופה עם שנה ישנה מדי"""
    try:
        period_service.create_period(test_client['client_id'], 2020, 1)
        report("שנה ישנה מדי", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שנה ישנה מדי", True)
 
def test_create_period_invalid_year_too_far():
    """יצירת תקופה עם שנה רחוקה מדי"""
    try:
        period_service.create_period(test_client['client_id'], 2099, 1)
        report("שנה רחוקה מדי", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שנה רחוקה מדי", True)
  
def test_create_period_invalid_number_zero():
    """יצירת תקופה עם מספר 0"""
    try:
        period_service.create_period(test_client['client_id'], 2026, 0)
        report("מספר תקופה 0", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תקופה 0", True)
 
def test_create_period_invalid_number_seven():
    """יצירת תקופה עם מספר 7 (מעבר ל-6)"""
    try:
        period_service.create_period(test_client['client_id'], 2026, 7)
        report("מספר תקופה 7", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תקופה 7", True)
 
def test_create_period_invalid_number_negative():
    """יצירת תקופה עם מספר שלילי"""
    try:
        period_service.create_period(test_client['client_id'], 2026, -1)
        report("מספר תקופה שלילי", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תקופה שלילי", True)
 
def test_create_period_nonexistent_client():
    """יצירת תקופה ללקוח שלא קיים"""
    try:
        period_service.create_period(99999, 2026, 1)
        report("לקוח לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("לקוח לא קיים", True)
        except AssertionError as ae:
            report("לקוח לא קיים", False, str(ae))
 
 
#  2. UNIQUENESS - duplicate 
 
def test_create_duplicate_period():
    """יצירת תקופה כפולה : אותו תאגיד + שנה + מספר"""
    try:
        period_service.create_period(test_client['client_id'], 2026, 1)
        period_service.create_period(test_client['client_id'], 2026, 1)
        report("תקופה כפולה", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "כבר קיימת" in str(e)
            report("תקופה כפולה", True)
        except AssertionError as ae:
            report("תקופה כפולה", False, str(ae))
 
def test_initialize_twice_skips_existing():
    """אתחול תקופות פעמיים לאותה שנה : צריך לדלג על קיימות"""
    try:
        # First time - period 1 already exists from previous test
        # Create remaining periods
        periods_first = period_service.initialize_periods_for_year(test_client['client_id'], 2026)
    
        # Second time - all 6 exist, should create 0
        periods_second = period_service.initialize_periods_for_year(test_client['client_id'], 2026)
        assert len(periods_second) == 0
        report("אתחול כפול מדלג על קיימות", True)
    except AssertionError as e:
        report("אתחול כפול מדלג על קיימות", False, str(e))

def test_initialize_different_year_allowed():
    """אתחול תקופות לשנה אחרת : צריך לעבוד"""
    try:
        periods = period_service.initialize_periods_for_year(test_client['client_id'], 2025)
        assert len(periods) == 6
        report("אתחול לשנה אחרת מותר", True)
    except AssertionError as e:
        report("אתחול לשנה אחרת מותר", False, str(e))
 
#  3. PREVIOUS PERIOD LOOKUP : edge cases
 
def test_previous_period_normal():
    """תקופה קודמת ל-3 היא 2 באותה שנה"""
    try:
        period_3 = period_service.get_period_by_identity(test_client['client_id'], 2026, 3)
        previous = period_service.get_previous_period(period_3['period_id'])
        assert previous is not None
        assert previous['period_number'] == 2
        assert previous['year'] == 2026
        report("תקופה קודמת ל-3 = תקופה 2", True)
    except AssertionError as e:
        report("תקופה קודמת ל-3 = תקופה 2", False, str(e))
 
def test_previous_period_crosses_year():
    """תקופה קודמת ל-1/2026 היא 6/2025 (חוצה שנה)"""
    try:
        period_1_2026 = period_service.get_period_by_identity(test_client['client_id'], 2026, 1)
        previous = period_service.get_previous_period(period_1_2026['period_id'])
        assert previous is not None
        assert previous['period_number'] == 6
        assert previous['year'] == 2025
        report("תקופה קודמת ל-1/2026 = 6/2025 (חוצה שנה)", True)
    except AssertionError as e:
        report("תקופה קודמת ל-1/2026 = 6/2025 (חוצה שנה)", False, str(e))
 
def test_previous_period_not_found():
    """תקופה קודמת ל-1/2025 : אין שנת 2024 → None"""
    try:
        period_1_2025 = period_service.get_period_by_identity(test_client['client_id'], 2025, 1)
        previous = period_service.get_previous_period(period_1_2025['period_id'])
        assert previous is None
        report("אין תקופה קודמת ל-1/2025 (None)", True)
    except AssertionError as e:
        report("אין תקופה קודמת ל-1/2025 (None)", False, str(e))
 
def test_previous_period_nonexistent():
    """שליפת תקופה קודמת לתקופה שלא קיימת"""
    try:
        period_service.get_previous_period(99999)
        report("תקופה קודמת לתקופה לא קיימת", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצאה" in str(e)
            report("תקופה קודמת לתקופה לא קיימת", True)
        except AssertionError as ae:
            report("תקופה קודמת לתקופה לא קיימת", False, str(ae))
 

#  4. STATUS TRANSITIONS : invalid moves
 
def test_activate_from_pending():
    """ניסיון להפעיל תקופה ישירות מ-pending (צריך file_received קודם)"""
    period = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)
    try:
        period_service.activate_period(period['period_id'])
        report("activate מ-pending", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא ניתן לעבור" in str(e)
            report("activate מ-pending (חסום)", True)
        except AssertionError as ae:
            report("activate מ-pending (חסום)", False, str(ae))
 
def test_complete_from_pending():
    """ניסיון להשלים תקופה מ-pending"""
    period = period_service.get_period_by_identity(test_client['client_id'], 2026, 3)
    try:
        period_service.complete_period(period['period_id'])
        report("complete מ-pending", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא ניתן לעבור" in str(e)
            report("complete מ-pending (חסום)", True)
        except AssertionError as ae:
            report("complete מ-pending (חסום)", False, str(ae))
 
def test_skip_from_file_received():
    """ניסיון לדלג על תקופה שכבר קיבלה קובץ"""
    period = period_service.get_period_by_identity(test_client['client_id'], 2026, 4)
    period_service.mark_file_received(period['period_id'])
    try:
        period_service.skip_period(period['period_id'])
        report("skip מ-file_received", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא ניתן לעבור" in str(e)
            report("skip מ-file_received (חסום)", True)
        except AssertionError as ae:
            report("skip מ-file_received (חסום)", False, str(ae))
 
def test_valid_status_flow():
    """מעבר סטטוסים תקין: pending → file_received → active → completed"""
    try:
        period = period_service.get_period_by_identity(test_client['client_id'], 2026, 5)

        period_service.mark_file_received(period['period_id'])
        updated = period_service.get_period(period['period_id'])
        assert updated['status'] == 'file_received'

        period_service.activate_period(period['period_id'])
        updated = period_service.get_period(period['period_id'])
        assert updated['status'] == 'active'

        period_service.complete_period(period['period_id'])
        updated = period_service.get_period(period['period_id'])
        assert updated['status'] == 'completed'

        report("מעבר סטטוסים תקין (pending→file_received→active→completed)", True)
    except AssertionError as e:
        report("מעבר סטטוסים תקין (pending→file_received→active→completed)", False, str(e))
 
def test_complete_already_completed():
    """ניסיון להשלים תקופה שכבר הושלמה"""
    period = period_service.get_period_by_identity(test_client['client_id'], 2026, 5)
    try:
        period_service.complete_period(period['period_id'])
        report("complete על completed", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא ניתן לעבור" in str(e) or "סופי" in str(e)
            report("complete על completed (חסום)", True)
        except AssertionError as ae:
            report("complete על completed (חסום)", False, str(ae))
 
def test_skip_period_from_pending():
    """דילוג על תקופה מ-pending : צריך להצליח"""
    try:
        period = period_service.get_period_by_identity(test_client['client_id'], 2026, 6)
        result = period_service.skip_period(period['period_id'])
        assert result is True
        updated = period_service.get_period(period['period_id'])
        assert updated['status'] == 'skipped'
        report("skip מ-pending (מותר)", True)
    except AssertionError as e:
        report("skip מ-pending (מותר)", False, str(e))
 
def test_update_status_manually_bypasses_transitions():
    """update_status_manually עוקפת ולידציית מעברים - קפיצה ישירה מותרת"""
    try:
        m_client = client_service.create_client("עיריית עדכון ידני", "100000005")
        period = period_service.create_period(m_client['client_id'], 2026, 1)
        assert period['status'] == 'pending'

        # קפיצה ישירה pending -> completed, שהייתה נחסמת ע"י complete_period הרגילה
        updated = period_service.update_status_manually(period['period_id'], 'completed')
        assert updated['status'] == 'completed'
        report("update_status_manually - קפיצה ישירה מותרת", True)
    except AssertionError as e:
        report("update_status_manually - קפיצה ישירה מותרת", False, str(e))

    # סטטוס לא חוקי בכלל
    try:
        period_service.update_status_manually(period['period_id'], 'not_a_real_status')
        report("update_status_manually - סטטוס לא חוקי (חסום)", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא חוקי" in str(e)
            report("update_status_manually - סטטוס לא חוקי (חסום)", True)
        except AssertionError as ae:
            report("update_status_manually - סטטוס לא חוקי (חסום)", False, str(ae))

    # תקופה שלא קיימת
    try:
        period_service.update_status_manually(99999, 'active')
        report("update_status_manually - תקופה לא קיימת (חסום)", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצאה" in str(e)
            report("update_status_manually - תקופה לא קיימת (חסום)", True)
        except AssertionError as ae:
            report("update_status_manually - תקופה לא קיימת (חסום)", False, str(ae))
 
#  5. INITIALIZE WITH start_from_period
 
def test_initialize_with_start_from():
    """אתחול עם start_from_period=3 : תקופות 1-2 צריכות להיות skipped"""
    try:
        new_client = client_service.create_client("עיריית חצי שנה", "100000002")
        periods = period_service.initialize_periods_for_year(new_client['client_id'], 2026, start_from_period=3)
        assert len(periods) == 6

        skipped = [p for p in periods if p['status'] == 'skipped']
        pending = [p for p in periods if p['status'] == 'pending']
        assert len(skipped) == 2
        assert len(pending) == 4
        report("אתחול עם start_from_period=3 (2 skipped, 4 pending)", True)
    except AssertionError as e:
        report("אתחול עם start_from_period=3 (2 skipped, 4 pending)", False, str(e))
 
def test_initialize_invalid_start_from():
    """אתחול עם start_from_period לא תקין"""
    new_client = client_service.create_client("עיריית מספר רע", "100000003")
    try:
        period_service.initialize_periods_for_year(new_client['client_id'], 2026, start_from_period=8)
        report("start_from_period=8", False, "לא נזרקה שגיאה")
    except ValueError:
        report("start_from_period=8 (חסום)", True)
 
#  6. NOT FOUND
 
def test_get_nonexistent_period():
    """שליפת תקופה שלא קיימת"""
    try:
        result = period_service.get_period(99999)
        assert result is None
        report("שליפת תקופה לא קיימת", True)
    except AssertionError as e:
        report("שליפת תקופה לא קיימת", False, str(e))
 
def test_mark_file_received_nonexistent():
    """סימון file_received לתקופה שלא קיימת"""
    try:
        period_service.mark_file_received(99999)
        report("file_received לתקופה לא קיימת", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצאה" in str(e)
            report("file_received לתקופה לא קיימת (חסום)", True)
        except AssertionError as ae:
            report("file_received לתקופה לא קיימת (חסום)", False, str(ae))
 
def test_delete_period():
    """מחיקת תקופה : לא קיימת (חסום), וקיימת עם הצלחה אמיתית (CASCADE)"""

    # nonexistent period: 
    try:
        period_service.delete_period(99999)
        report("מחיקת תקופה לא קיימת", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצאה" in str(e)
            report("מחיקת תקופה לא קיימת", True)
        except AssertionError as ae:
            report("מחיקת תקופה לא קיימת", False, str(ae))
    
    # exist period:
    try:
        del_client = client_service.create_client("עיריית מחיקה", "100000004")
        period = period_service.create_period(del_client['client_id'], 2026, 1)

        result = period_service.delete_period(period['period_id'])
        assert result is True

        fetched = period_service.get_period(period['period_id'])
        assert fetched is None
        report("מחיקת תקופה קיימת (הצלחה)", True)
    except AssertionError as e:
        report("מחיקת תקופה קיימת (הצלחה)", False, str(e))
 
#  RUN ALL TESTS
 
def main():
    global passed, failed
 
    print("=" * 50)
    print("  Monim tests : Reading Period Error Tests")
    print("=" * 50)
 
    try: 
        # Setup
        print("\n=== הכנה ===")
        setup()
    
        # 1. Validation
        print("\n=== בדיקות ולידציה : קלט לא תקין ===")
        test_create_period_invalid_year_too_old()
        test_create_period_invalid_year_too_far()
        test_create_period_invalid_number_zero()
        test_create_period_invalid_number_seven()
        test_create_period_invalid_number_negative()
        test_create_period_nonexistent_client()
    
        # 2. Uniqueness
        print("\n=== בדיקות ייחודיות : כפילויות ===")
        test_create_duplicate_period()
        test_initialize_twice_skips_existing()
        test_initialize_different_year_allowed()
    
        # 3. Previous period
        print("\n=== בדיקות תקופה קודמת ===")
        test_previous_period_normal()
        test_previous_period_crosses_year()
        test_previous_period_not_found()
        test_previous_period_nonexistent()
    
        # 4. Status transitions
        print("\n=== בדיקות מעברי סטטוס ===")
        test_activate_from_pending()
        test_complete_from_pending()
        test_skip_from_file_received()
        test_valid_status_flow()
        test_complete_already_completed()
        test_skip_period_from_pending()
        test_update_status_manually_bypasses_transitions()
    
        # 5. Initialize with start_from
        print("\n=== בדיקות אתחול עם start_from_period ===")
        test_initialize_with_start_from()
        test_initialize_invalid_start_from()
    
        # 6. Not found
        print("\n=== בדיקות רשומה לא קיימת ===")
        test_get_nonexistent_period()
        test_mark_file_received_nonexistent()
        test_delete_period()
 
        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)
   
    finally: 
        # Cleanup
        cleanup()
 
 
if __name__ == "__main__":
    main()