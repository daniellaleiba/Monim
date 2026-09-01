"""
Monim : Client Error Tests
Testing edge cases, validation, and error handling for Client entity.
Each test tries to break something, PASS means the system protected itself.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
 
from src.services.client_service import ClientService
from src.services.reading_period_service import ReadingPeriodService
from src.services.folder_template_service import FolderTemplateService
from tests.test_helpers import report, print_summary, cleanup, reset_counters
 
client_service = ClientService()
 
#  1. VALIDATION ERRORS : bad input that should be rejected
 
def test_create_client_empty_name():
    """יצירת לקוח עם שם ריק"""
    try:
        client_service.create_client("", "111111111")
        report("שם ריק", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שם ריק", True)
 
def test_create_client_no_name():
    """יצירת לקוח בלי שם (None)"""
    try:
        client_service.create_client(None, "111111112")
        report("שם None", False, "לא נזרקה שגיאה")
    except (ValueError, TypeError, AttributeError):
        report("שם None", True)
 
def test_create_client_no_corp_number():
    """יצירת לקוח בלי מספר תאגיד (None)"""
    try:
        client_service.create_client("עיריית מספר None", None)
        report("מספר תאגיד None", False, "לא נזרקה שגיאה")
    except (ValueError, TypeError, AttributeError):
        report("מספר תאגיד None", True)

def test_create_client_short_name():
    """יצירת לקוח עם שם קצר מדי (תו אחד)"""
    try:
        client_service.create_client("א", "111111113")
        report("שם קצר מדי", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שם קצר מדי", True)
 
def test_create_client_name_too_long():
    """יצירת לקוח עם שם ארוך מדי (מעל 100 תווים)"""
    try:
        long_name = "א" * 101
        client_service.create_client(long_name, "760000001")
        report("שם ארוך מדי", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שם ארוך מדי", True)

def test_create_client_invalid_corp_number_letters():
    """יצירת לקוח עם מספר תאגיד שמכיל אותיות"""
    try:
        client_service.create_client("עיריית בדיקה", "ABC123")
        report("מספר תאגיד עם אותיות", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תאגיד עם אותיות", True)
  
def test_create_client_invalid_corp_number_too_long():
    """יצירת לקוח עם מספר תאגיד ארוך מדי (יותר מ-9 ספרות)"""
    try:
        client_service.create_client("עיריית בדיקה", "1234567890")
        report("מספר תאגיד ארוך מדי", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תאגיד ארוך מדי", True)
 
def test_create_client_empty_corp_number():
    """יצירת לקוח עם מספר תאגיד ריק"""
    try:
        client_service.create_client("עיריית בדיקה", "")
        report("מספר תאגיד ריק", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תאגיד ריק", True)

#  2. UNIQUENESS ERRORS : duplicates that should be blocked
 
def test_create_duplicate_name():
    """יצירת שני לקוחות עם אותו שם"""
    try:
        client_service.create_client("עיריית כפילות", "200000001")
        client_service.create_client("עיריית כפילות", "200000002")
        report("שם כפול", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "כבר קיים" in str(e)
        report("שם כפול", True)
 
def test_create_duplicate_corp_number():
    """יצירת שני לקוחות עם אותו מספר תאגיד"""
    try:
        client_service.create_client("עיריית ראשונה", "300000001")
        client_service.create_client("עיריית שנייה", "300000001")
        report("מספר תאגיד כפול", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "כבר קיים" in str(e)
        report("מספר תאגיד כפול", True)
 
def test_update_name_to_existing():
    """עדכון לקוח לשם שכבר קיים אצל לקוח אחר"""
    try:
        c1 = client_service.create_client("עיריית עדכון א", "400000001")
        c2 = client_service.create_client("עיריית עדכון ב", "400000002")
        client_service.update_client(c2['client_id'], name="עיריית עדכון א")
        report("עדכון שם לקיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "כבר קיים" in str(e)
        report("עדכון שם לקיים", True)

def test_update_corp_number_to_existing():
    """עדכון לקוח למספר תאגיד שכבר קיים"""
    try:
        c1 = client_service.create_client("עיריית תאגיד א", "500000001")
        c2 = client_service.create_client("עיריית תאגיד ב", "500000002")
        client_service.update_client(c2['client_id'], corporation_number="500000001")
        report("עדכון מספר תאגיד לקיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "כבר קיים" in str(e)
        report("עדכון מספר תאגיד לקיים", True)
 
def test_update_same_name_allowed():
    """עדכון לקוח עם השם שלו עצמו, צריך להצליח"""
    try:
        c = client_service.create_client("עיריית ללא שינוי", "600000001")
        result = client_service.update_client(c['client_id'], name="עיריית ללא שינוי")
        assert result is True
        report("עדכון עם שם עצמי (מותר)", True)
    except ValueError:
        report("עדכון עם שם עצמי (מותר)", False, "נזרקה שגיאה על שם עצמי")
    except AssertionError as e:
        report("עדכון עם שם עצמי (מותר)", False, str(e))
 
def test_update_same_corp_number_allowed():
    """עדכון לקוח עם מספר התאגיד שלו עצמו, צריך להצליח"""
    try:
        c = client_service.create_client("עיריית תאגיד ללא שינוי", "750000001")
        result = client_service.update_client(c['client_id'], corporation_number="750000001")
        assert result is True
        report("עדכון עם מספר תאגיד עצמי (מותר)", True)
    except ValueError:
        report("עדכון עם מספר תאגיד עצמי (מותר)", False, "נזרקה שגיאה על מספר עצמי")

#  3. UPDATE ERRORS : bad update inputs
 
def test_update_no_fields():
    """עדכון לקוח בלי להעביר אף שדה, צריך להחזיר False"""
    c = client_service.create_client("עיריית ריקה", "610000001")
    try:
        result = client_service.update_client(c['client_id'])
        assert result is False
        report("עדכון בלי שדות", True)
    except AssertionError as e:
        report("עדכון בלי שדות", False, str(e))
 
def test_update_empty_name():
    """עדכון לקוח עם שם ריק"""
    try:
        c = client_service.create_client("עיריית שם ריק", "620000001")
        client_service.update_client(c['client_id'], name="")
        report("עדכון שם ריק", False, "לא נזרקה שגיאה")
    except ValueError:
        report("עדכון שם ריק", True)
 
def test_update_spaces_only_name():
    """עדכון לקוח עם שם שמכיל רק רווחים"""
    try:
        c = client_service.create_client("עיריית רווחים", "630000001")
        client_service.update_client(c['client_id'], name="   ")
        report("עדכון שם רווחים בלבד", False, "לא נזרקה שגיאה")
    except ValueError:
        report("עדכון שם רווחים בלבד", True)
 
def test_update_invalid_corp_number():
    """עדכון לקוח עם מספר תאגיד לא תקין"""
    try:
        c = client_service.create_client("עיריית תאגיד רע", "640000001")
        client_service.update_client(c['client_id'], corporation_number="ABCDEF")
        report("עדכון מספר תאגיד לא תקין", False, "לא נזרקה שגיאה")
    except ValueError:
        report("עדכון מספר תאגיד לא תקין", True)
 
#  4. NORMALIZATION : trimming and cleaning
 
def test_create_name_with_spaces_trimmed():
    """יצירת לקוח עם רווחים בשם, צריך להיות מנוקה"""
    c = client_service.create_client("  עיריית נרמול רווחים  ", "650000001")
    try:
        assert c['name'] == "עיריית נרמול רווחים"
        report("שם עם רווחים מנוקה", True)
    except AssertionError as e:
        report("שם עם רווחים מנוקה", False, str(e))
 
def test_create_corp_number_with_dashes_cleaned():
    """יצירת לקוח עם מקפים במספר תאגיד, צריך להיות מנוקה"""
    c = client_service.create_client("עיריית מקפים", "660-000-001")
    try:
        assert c['corporation_number'] == "660000001"
        report("מספר תאגיד עם מקפים מנוקה", True)
    except AssertionError as e:
        report("מספר תאגיד עם מקפים מנוקה", False, str(e))
 
def test_create_corp_number_with_spaces_cleaned():
    """יצירת לקוח עם רווחים במספר תאגיד, צריך להיות מנוקה"""
    c = client_service.create_client("עיריית רווחי תאגיד", "670 000 001")
    try:
        assert c['corporation_number'] == "670000001"
        report("מספר תאגיד עם רווחים מנוקה", True)
    except AssertionError as e:
        report("מספר תאגיד עם רווחים מנוקה", False, str(e))
 
def test_trimmed_name_duplicate_detected():
    """שם עם רווחים שאחרי ניקוי זהה לשם קיים, צריך להיחסם ככפילות"""
    try:
        client_service.create_client("עיריית כפילות רווח", "680000001")
        client_service.create_client("  עיריית כפילות רווח  ", "680000002")
        report("כפילות שם אחרי trim", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "כבר קיים" in str(e)
        report("כפילות שם אחרי trim", True)
 
def test_cleaned_corp_number_duplicate_detected():
    """מספר תאגיד עם מקפים שאחרי ניקוי זהה לקיים, צריך להיחסם"""
    try:
        client_service.create_client("עיריית תאגיד נקי", "690000001")
        client_service.create_client("עיריית תאגיד מקפים", "690-000-001")
        report("כפילות מספר תאגיד אחרי ניקוי", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "כבר קיים" in str(e)
        report("כפילות מספר תאגיד אחרי ניקוי", True)
 
def test_create_client_whitespace_city_normalized_to_none():
    """יצירת לקוח עם city של רווחים בלבד, צריך להישמר כ-None ולא כמחרוזת ריקה"""
    c = client_service.create_client("עיריית עיר רווחים", "710000001", city="   ")
    try:
        assert c['city'] is None
        report("city רווחים בלבד מנורמל ל-None (create)", True)
    except AssertionError as e:
        report("city רווחים בלבד מנורמל ל-None (create)", False, str(e))

def test_update_client_whitespace_city_normalized_to_none():
    """עדכון לקוח ל-city של רווחים בלבד, צריך להישמר כ-None ולא כמחרוזת ריקה"""
    c = client_service.create_client("עיריית עיר לעדכון", "720000001", city="תל אביב")
    try:
        client_service.update_client(c['client_id'], city="   ")
        fetched = client_service.get_client(c['client_id'])
        assert fetched['city'] is None
        report("city רווחים בלבד מנורמל ל-None (update)", True)
    except AssertionError as e:
        report("city רווחים בלבד מנורמל ל-None (update)", False, str(e))

def test_update_client_omit_city_leaves_unchanged():
    """אי-העברת city בעדכון לא נוגעת בערך הקיים"""
    c = client_service.create_client("עיריית עיר קיימת", "730000001", city="חיפה")
    try:
        client_service.update_client(c['client_id'], name="עיריית עיר קיימת2")  # city לא מועבר
        fetched = client_service.get_client(c['client_id'])
        assert fetched['city'] == "חיפה"
        report("אי-העברת city משאירה ערך קיים", True)
    except AssertionError as e:
        report("אי-העברת city משאירה ערך קיים", False, str(e))

#  5. NOT FOUND ERRORS : operations on non-existent records
 
def test_get_nonexistent_client():
    """שליפת לקוח שלא קיים"""
    try:
        result = client_service.get_client(99999)
        assert result is None
        report("שליפת לקוח לא קיים", True)
    except AssertionError as e:
        report("שליפת לקוח לא קיים", False, str(e))
 
def test_update_nonexistent_client():
    """עדכון לקוח שלא קיים"""
    try:
        client_service.update_client(99999, name="שם חדש")
        report("עדכון לקוח לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "לא נמצא" in str(e)
        report("עדכון לקוח לא קיים", True)
 
def test_delete_nonexistent_client():
    """מחיקת לקוח שלא קיים"""
    try:
        client_service.delete_client(99999)
        report("מחיקת לקוח לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "לא נמצא" in str(e)
        report("מחיקת לקוח לא קיים", True)
 
#  6. DEPENDENCY CHECKS : delete client with related data
 
def test_delete_client_with_periods():
    """מחיקת לקוח עם תקופות קיימות, צריכה להיחסם"""
    period_service = ReadingPeriodService()
    c = client_service.create_client("עיריית למחיקה", "700000001")
    period_service.initialize_periods_for_year(c['client_id'], 2026)
    try:
        client_service.delete_client(c['client_id'])
        report("מחיקת לקוח עם תקופות (חסום)", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "תקופות" in str(e)
        report("מחיקת לקוח עם תקופות (חסום)", True)
  
def test_delete_client_with_templates():
    """מחיקת לקוח עם תבניות קיימות, צריכה להיחסם"""
    template_service = FolderTemplateService()
    c = client_service.create_client("עיריית תבניות", "800000001")
    template_service.create_template(c['client_id'], 1, "תיק א", 1000, 2000)
    try:
        client_service.delete_client(c['client_id'])
        report("מחיקת לקוח עם תבניות (חסום)", False, "לא נזרקה שגיאה")
    except ValueError as e:
        assert "תבניות" in str(e)
        report("מחיקת לקוח עם תבניות (חסום)", True)
 
def test_delete_clean_client():
    """מחיקת לקוח נקי בלי תלויות - צריך להצליח"""
    c = client_service.create_client("עיריית נקייה", "900000001")
    try:
        result = client_service.delete_client(c['client_id'])
        assert result is True
        
        # Verify it's gone
        fetched = client_service.get_client(c['client_id'])
        assert fetched is None
        report("מחיקת לקוח נקי", True)
    except AssertionError as e:
        report("מחיקת לקוח נקי", False, str(e))
 
 
#  RUN ALL TESTS
 
def main():
    global passed, failed
 
    print("=" * 50)
    print("  Monim V2 : Client Error Tests")
    print("=" * 50)

    try:
 
        # 1. Validation
        print("\n=== בדיקות ולידציה: קלט לא תקין ===")
        test_create_client_empty_name()
        test_create_client_no_name()
        test_create_client_no_corp_number()
        test_create_client_short_name()
        test_create_client_name_too_long()
        test_create_client_invalid_corp_number_letters()
        test_create_client_invalid_corp_number_too_long()
        test_create_client_empty_corp_number()
    
        # 2. Uniqueness
        print("\n=== בדיקות ייחודיות : כפילויות שצריכות להיחסם ===")
        test_create_duplicate_name()
        test_create_duplicate_corp_number()
        test_update_name_to_existing()
        test_update_corp_number_to_existing()
        test_update_same_name_allowed()
        test_update_same_corp_number_allowed()
    
        # 3. Update errors
        print("\n=== בדיקות עדכון : קלט לא תקין ===")
        test_update_no_fields()
        test_update_empty_name()
        test_update_spaces_only_name()
        test_update_invalid_corp_number()
    
        # 4. Normalization
        print("\n=== בדיקות נרמול : ניקוי קלט ===")
        test_create_name_with_spaces_trimmed()
        test_create_corp_number_with_dashes_cleaned()
        test_create_corp_number_with_spaces_cleaned()
        test_trimmed_name_duplicate_detected()
        test_cleaned_corp_number_duplicate_detected()
        test_create_client_whitespace_city_normalized_to_none()
        test_update_client_whitespace_city_normalized_to_none()
        test_update_client_omit_city_leaves_unchanged()
    
        # 5. Not found
        print("\n=== בדיקות רשומה לא קיימת ===")
        test_get_nonexistent_client()
        test_update_nonexistent_client()
        test_delete_nonexistent_client()
    
        # 6. Dependencies
        print("\n=== בדיקות תלויות : מחיקה עם נתונים קשורים ===")
        test_delete_client_with_periods()
        test_delete_client_with_templates()
        test_delete_clean_client()
    
        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()
 
if __name__ == "__main__":
    main()