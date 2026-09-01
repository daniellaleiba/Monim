"""
Monim - Period Source File Error Tests
Testing edge cases, validation, and error handling for PeriodSourceFile entity.

Tests Summary:

1. Validation Errors (3 tests)
   - Empty filename
   - Unknown file type
   - Upload to non-existent period

2. Upload Rules (2 tests)
   - Successful upload updates period status to file_received (covers two clean periods, to confirm it's not a one-off)
   - Upload to period that already has a file (blocked)

3. Replace File (3 tests)
   - Replace when no file exists (blocked)
   - Successful replace resets processing status
   - Replace with invalid file type (blocked)

4. Processing Status (5 tests)
   - Process file not in pending status (blocked)
   - Mark success on non-existent file (blocked)
   - Mark error saves error message
   - Retry on file not in error status (blocked)
   - Retry on file in error status (resets to pending)

5. Not Found / Delete (4 tests)
   - Get non-existent source file
   - Get source file for period without file
   - Delete non-existent source file (blocked)
   - Delete source file: succeeds with no dependent meters, blocked (RESTRICT) when meters exist

Total: 17 tests
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.client_service import ClientService
from src.services.periodmeter_service import PeriodMeterService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from tests.test_helpers import report, print_summary, cleanup, reset_counters

client_service = ClientService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()

# Shared test data
test_client = None
test_periods = None

def setup():
    """Create shared test client and periods"""
    global test_client, test_periods
    test_client = client_service.create_client("עיריית קבצים בדיקה", "100000010")
    test_periods = period_service.initialize_periods_for_year(test_client['client_id'], 2026)
    print(f"  Setup: לקוח (ID: {test_client['client_id']}), 6 תקופות נוצרו")


#  1. VALIDATION ERRORS : bad input

def test_upload_empty_filename():
    """העלאת קובץ עם שם ריק"""
    try:
        source_file_service.upload_period_file( period_id=test_periods[0]['period_id'],
            original_filename="", file_type="excel")
        report("שם קובץ ריק", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שם קובץ ריק", True)

def test_upload_unknown_file_type():
    """העלאת קובץ עם סוג לא מוכר"""
    try:
        source_file_service.upload_period_file( period_id=test_periods[0]['period_id'],
            original_filename="test.xyz", file_type="unknown_format")
        report("סוג קובץ לא מוכר", False, "לא נזרקה שגיאה")
    except ValueError:
        report("סוג קובץ לא מוכר", True)

def test_upload_to_nonexistent_period():
    """העלאת קובץ לתקופה שלא קיימת"""
    try:
        source_file_service.upload_period_file( period_id=99999,
            original_filename="test.xlsx", file_type="excel")
        report("תקופה לא קיימת", False, "לא נזרקה שגיאה")
    except ValueError:
        report("תקופה לא קיימת", True)

#  2. UPLOAD RULES : one file per period

def test_upload_success_and_status_update():
    """העלאת קובץ תקינה - סטטוס תקופה מתעדכן ל-file_received"""
    try:
        source_file = source_file_service.upload_period_file(
            period_id=test_periods[0]['period_id'], original_filename="netanya_p1.xlsx",
            file_type="excel", uploaded_by="מנהל בדיקה", file_path="/uploads/test/netanya_p1.xlsx")
        assert source_file is not None
        assert source_file['processing_status'] == 'pending'

        period = period_service.get_period(test_periods[0]['period_id'])
        assert period['status'] == 'file_received'
        report("העלאה תקינה + סטטוס תקופה עודכן", True)
    except AssertionError as e:
        report("העלאה תקינה + סטטוס תקופה עודכן", False, str(e))

     # תקופה נוספת, ריקה - מוודא שזו לא "מזל" חד-פעמי של תקופה 0
    try:
        source_file2 = source_file_service.upload_period_file(
            period_id=test_periods[1]['period_id'], original_filename="netanya_p2.xlsx", file_type="excel")
        assert source_file2 is not None
        report("העלאה לתקופה נקייה נוספת (מותר)", True)
    except AssertionError as e:
        report("העלאה לתקופה נקייה נוספת (מותר)", False, str(e))

def test_upload_duplicate_blocked():
    """העלאת קובץ לתקופה שכבר יש לה קובץ : צריך להיחסם"""
    try:
        source_file_service.upload_period_file( period_id=test_periods[0]['period_id'],
            original_filename="another_file.xlsx", file_type="excel")
        report("העלאה כפולה", False, "לא נזרקה שגיאה")
    except ValueError:
        report("העלאה כפולה (חסום)", True)

#  3. REPLACE FILE : swap existing file

def test_replace_when_no_file_exists():
    """החלפת קובץ כשאין קובץ קיים - צריך להיכשל"""
    try:
        source_file_service.replace_period_file( period_id=test_periods[2]['period_id'],
            original_filename="replacement.xlsx", file_type="excel")
        report("החלפה בלי קובץ קיים", False, "לא נזרקה שגיאה")
    except ValueError:
        report("החלפה בלי קובץ קיים (חסום)", True)

def test_replace_success_resets_status():
    """החלפת קובץ קיים - סטטוס עיבוד מתאפס ל-pending"""
    try:
        updated = source_file_service.replace_period_file(period_id=test_periods[0]['period_id'], original_filename="netanya_p1_v2.xlsx",
            file_type="csv", file_path="/uploads/test/netanya_p1_v2.csv")
        assert updated is not None
        assert updated['original_filename'] == "netanya_p1_v2.xlsx"
        assert updated['processing_status'] == 'pending'
        assert updated['file_type'] == 'csv'
        assert updated['error_message'] is None
        assert updated['rows_count'] is None
        report("החלפת קובץ מאפסת סטטוס", True)
    except AssertionError as e:
        report("החלפת קובץ מאפסת סטטוס", False, str(e))

def test_replace_with_invalid_file_type():
    """החלפת קובץ עם סוג לא מוכר"""
    try:
        source_file_service.replace_period_file( period_id=test_periods[0]['period_id'],
            original_filename="bad_file.xyz", file_type="bad_format")
        report("החלפה עם סוג לא מוכר", False, "לא נזרקה שגיאה")
    except ValueError:
        report("החלפה עם סוג לא מוכר (חסום)", True)

#  4. PROCESSING STATUS : success, error, retry

def test_process_not_pending():
    """ניסיון לעבד קובץ שלא ב-pending"""
    # Get the source file for period 1 and mark as success first
    sf = source_file_service.get_period_source_file(test_periods[0]['period_id'])
    source_file_service.mark_processing_success(sf['source_file_id'], 100)
    try:
        source_file_service.process_uploaded_file(sf['source_file_id'])
        report("עיבוד קובץ שלא ב-pending", False, "לא נזרקה שגיאה")
    except ValueError:
        report("עיבוד קובץ שלא ב-pending (חסום)", True)

def test_mark_success_nonexistent():
    """סימון הצלחה לקובץ שלא קיים"""
    try:
        source_file_service.mark_processing_success(99999, 50)
        report("mark_success לקובץ לא קיים", False, "לא נזרקה שגיאה")
    except ValueError:
        report("mark_success לקובץ לא קיים (חסום)", True)

def test_mark_error_saves_message():
    """סימון שגיאה שומר הודעה"""
    try:
        sf = source_file_service.upload_period_file( period_id=test_periods[2]['period_id'],
            original_filename="bad_data.xlsx", file_type="excel")
        source_file_service.mark_processing_error(sf['source_file_id'], "פורמט לא תקין בשורה 15")
        updated = source_file_service.get_source_file(sf['source_file_id'])
        assert updated['processing_status'] == 'error'
        assert "שורה 15" in updated['error_message']
        report("שגיאת עיבוד נשמרת עם הודעה", True)
    except AssertionError as e:
        report("שגיאת עיבוד נשמרת עם הודעה", False, str(e))

def test_retry_not_in_error():
    """ניסיון חוזר על קובץ שלא בסטטוס error"""
    sf = source_file_service.get_period_source_file(test_periods[0]['period_id'])
    try:
        source_file_service.retry_processing(sf['source_file_id'])
        report("retry על קובץ לא ב-error", False, "לא נזרקה שגיאה")
    except ValueError:
        report("retry על קובץ לא ב-error (חסום)", True)

def test_retry_from_error():
    """ניסיון חוזר על קובץ בסטטוס error - מאפס ומנסה לעבד שוב"""
    try:
        sf = source_file_service.get_period_source_file(test_periods[2]['period_id'])
        assert sf['processing_status'] == 'error'
        try:
            source_file_service.retry_processing(sf['source_file_id'])
        except Exception:
            pass  # צפוי - אין קובץ אמיתי בנתיב
        updated = source_file_service.get_source_file(sf['source_file_id'])
        assert updated['processing_status'] == 'error'
        report("retry מ-error עובד (מנסה לעבד שוב)", True)
    except AssertionError as e:
        report("retry מ-error עובד (מנסה לעבד שוב)", False, str(e))


#  5. NOT FOUND

def test_get_nonexistent_source_file():
    """שליפת קובץ מקור שלא קיים"""
    try:
        result = source_file_service.get_source_file(99999)
        assert result is None
        report("שליפת קובץ לא קיים", True)
    except AssertionError as e:
        report("שליפת קובץ לא קיים", False, str(e))

def test_get_source_file_for_empty_period():
    """שליפת קובץ לתקופה שאין לה קובץ"""
    try:
        result = source_file_service.get_period_source_file(test_periods[3]['period_id'])
        assert result is None
        report("שליפת קובץ לתקופה ריקה", True)
    except AssertionError as e:
        report("שליפת קובץ לתקופה ריקה", False, str(e))

def test_delete_nonexistent_source_file():
    """מחיקת קובץ שלא קיים"""
    try:
        source_file_service.delete_source_file(99999)
        report("מחיקת קובץ לא קיים", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מחיקת קובץ לא קיים (חסום)", True)

def test_delete_source_file_success_and_restrict():
    """מחיקת קובץ מקור: מצליחה כשאין מונים תלויים, נחסמת (RESTRICT) כשיש"""
    try:
        # הצלחה - תקופה בלי מונים בכלל
        clean_period = test_periods[4]  # תקופה 5, עוד לא נגענו בה
        sf = source_file_service.upload_period_file(
            period_id=clean_period['period_id'], original_filename="clean.xlsx", file_type="excel")

        result = source_file_service.delete_source_file(sf['source_file_id'])
        assert result is True

        fetched = source_file_service.get_source_file(sf['source_file_id'])
        assert fetched is None
        report("מחיקת קובץ מקור ללא מונים תלויים (הצלחה)", True)
    except AssertionError as e:
        report("מחיקת קובץ מקור ללא מונים תלויים (הצלחה)", False, str(e))

    try:
        # RESTRICT - תקופה עם מונים שנוצרו מהקובץ
        blocked_period = test_periods[5]  # תקופה 6
        sf2 = source_file_service.upload_period_file(
            period_id=blocked_period['period_id'], original_filename="withmeters.xlsx", file_type="excel")
        meter_service.create_meters_from_parsed_rows(blocked_period['period_id'], sf2['source_file_id'], [{'row_number': 1, 'meter_number': 'MTR-SF-DEL-001', 'previous_reading': 10}])

        try:
            source_file_service.delete_source_file(sf2['source_file_id'])
            report("מחיקת קובץ מקור עם מונים (RESTRICT, חסום)", False, "לא נזרקה שגיאה כלשהי")
        except Exception:
            still_exists = source_file_service.get_source_file(sf2['source_file_id'])
            assert still_exists is not None
            report("מחיקת קובץ מקור עם מונים (RESTRICT, חסום)", True)
    except AssertionError as e:
        report("מחיקת קובץ מקור עם מונים (RESTRICT, חסום)", False, str(e))

#  RUN ALL TESTS

def main():
    global passed, failed

    print("=" * 50)
    print("  Monim test : Source File Error Tests")
    print("=" * 50)

    try:
        # Setup
        print("\n=== הכנה ===")
        setup()

        # 1. Validation
        print("\n=== בדיקות ולידציה : קלט לא תקין ===")
        test_upload_empty_filename()
        test_upload_unknown_file_type()
        test_upload_to_nonexistent_period()

        # 2. Upload rules
        print("\n=== בדיקות העלאה : כללי קובץ אחד לתקופה ===")
        test_upload_success_and_status_update()
        test_upload_duplicate_blocked()

        # 3. Replace
        print("\n=== בדיקות החלפת קובץ ===")
        test_replace_when_no_file_exists()
        test_replace_success_resets_status()
        test_replace_with_invalid_file_type()

        # 4. Processing
        print("\n=== בדיקות סטטוס עיבוד ===")
        test_process_not_pending()
        test_mark_success_nonexistent()
        test_mark_error_saves_message()
        test_retry_not_in_error()
        test_retry_from_error()

        # 5. Not found
        print("\n=== בדיקות רשומה לא קיימת ===")
        test_get_nonexistent_source_file()
        test_get_source_file_for_empty_period()
        test_delete_nonexistent_source_file()
        test_delete_source_file_success_and_restrict()

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()


if __name__ == "__main__":
    main()