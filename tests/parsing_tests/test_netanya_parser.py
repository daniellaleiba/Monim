"""
Monim - Netanya Parser Tests
Testing parsing, normalization, validation, and error handling for NetanyaParser.

Note: These tests work on files only - no DB access needed.
      The parser reads Excel files and returns normalized dicts.
      Nothing is saved to the database.

Tests Summary:

1. Basic Parsing (3 tests)
   - Parser inherits from BaseParser
   - file_type returns 'netanya_format'
   - Sample file parsed correctly (10 rows)


2. Normalization (3 tests)
   - Row structure: required keys present, meter_number/customer_number are strings, customer_name is None, raw_data contains model
   - walk_order (int when present, None when missing) and previous_reading (float when present)
   - installation_date in YYYY-MM-DD format

3. Specific Values (1 test)
   - First row values match expected data

4. Validation (4 tests)
   - Valid rows pass validation
   - Missing meter_number detected
   - Empty meter_number detected
   - Negative previous_reading detected

5. Error Handling (4 tests)
   - File not found raises error
   - Empty file raises error
   - Header-only file raises error
   - Wrong headers raises error

6. # N/A Handling (2 tests)
   - #N/A in previous_reading becomes None
   - Valid row after #N/A row still works

Total: 22 tests
"""

import sys
import os
import openpyxl
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.parsers.base_parser import BaseParser
from src.parsers.netanya_parser import NetanyaParser
from tests.test_helpers import report, print_summary

# --- Test file paths ---
TEST_DIR = os.path.dirname(__file__)
SAMPLE_FILE = os.path.join(TEST_DIR, "test_data", "netanya_sample.xlsx")
EMPTY_FILE = os.path.join(TEST_DIR, "test_data", "empty_file.xlsx")
HEADER_ONLY_FILE = os.path.join(TEST_DIR, "test_data", "header_only.xlsx")
WRONG_HEADERS_FILE = os.path.join(TEST_DIR, "test_data", "wrong_headers.xlsx")
NA_FILE = os.path.join(TEST_DIR, "test_data", "na_values_temp.xlsx")


#  Shared state
parser = NetanyaParser()
sample_rows = None


def setup():
    """Parse sample file once for all tests"""
    global sample_rows
    sample_rows = parser.parse(SAMPLE_FILE)
    print(f"  Setup: נטען קובץ דוגמה עם {len(sample_rows)} שורות")

    # Show example normalized row so we can see what the parser produces
    print(f"\n  --- דוגמה לשורה מנורמלת (שורה 1) ---")
    row = sample_rows[0]
    for key, value in row.items():
        print(f"    {key}: {value}")
    print(f"  ---\n")

#  1. BASIC PARSING

def test_inherits_from_base_parser():
    """Parser יורש מ-BaseParser"""
    try:
        assert isinstance(parser, BaseParser)
        report("Parser יורש מ-BaseParser", True)
    except AssertionError as e:
        report("Parser יורש מ-BaseParser", False, str(e))

def test_file_type():
    """file_type מחזיר netanya_format"""
    try:
        assert parser.get_file_type() == "netanya_format"
        report("file_type = 'netanya_format'", True)
    except AssertionError as e:
        report("file_type = 'netanya_format'", False, str(e))

def test_parse_row_count():
    """קובץ דוגמה מחזיר 10 שורות"""
    try:
        assert len(sample_rows) == 10
        report(f"קובץ דוגמה → {len(sample_rows)} שורות (צפוי 10)", True)
    except AssertionError as e:
        report(f"קובץ דוגמה → {len(sample_rows)} שורות (צפוי 10)", False, str(e))

#  2. NORMALIZATION : types and structure

def test_row_structure():
    """שדות נדרשים, טיפוסים בסיסיים, ו-raw_data תקינים בכל שורה"""
    required_keys = ["row_number", "meter_number", "customer_number",
        "customer_name", "address", "walk_order", "previous_reading", "installation_date", "raw_data"]
    try:
        for row in sample_rows:
            rn = row.get('row_number')
            for key in required_keys:
                assert key in row, f"חסר שדה '{key}' בשורה {rn}"
            assert isinstance(row["meter_number"], str), f"meter_number לא string בשורה {rn} (type: {type(row['meter_number']).__name__})"
            if row["customer_number"] is not None:
                assert isinstance(row["customer_number"], str), f"customer_number לא string בשורה {rn}"
            assert row["customer_name"] is None, f"customer_name לא None בשורה {rn} (ערך: {row['customer_name']})"
            assert "model" in row["raw_data"], f"raw_data חסר 'model' בשורה {rn}"
        report("מבנה שורה: שדות, טיפוסים, raw_data תקינים", True)
    except AssertionError as e:
        report("מבנה שורה: שדות, טיפוסים, raw_data תקינים", False, str(e))

def test_walk_order_and_reading_types():
    """walk_order: int כשקיים/None כשחסר. previous_reading: float כשקיים"""
    row_with = next(r for r in sample_rows if r["walk_order"] is not None)
    row_without = next(r for r in sample_rows if r["walk_order"] is None)
    print(f"    דוגמה: שורה {row_with['row_number']} walk_order = {row_with['walk_order']} (int)")
    print(f"    דוגמה: שורה {row_without['row_number']} walk_order = None")
    try:
        assert isinstance(row_with["walk_order"], int), f"walk_order לא int בשורה {row_with['row_number']}"
        assert row_without["walk_order"] is None, f"walk_order אמור להיות None בשורה {row_without['row_number']}"
        for row in sample_rows:
            if row["previous_reading"] is not None:
                assert isinstance(row["previous_reading"], float), \
                    f"previous_reading לא float בשורה {row['row_number']} (type: {type(row['previous_reading']).__name__})"
        report("walk_order (int/None) ו-previous_reading (float) תקינים", True)
    except AssertionError as e:
        report("walk_order (int/None) ו-previous_reading (float) תקינים", False, str(e))

def test_installation_date_format():
    """תאריך התקנה בפורמט YYYY-MM-DD"""
    import re
    print(f"    דוגמה: שורה 1 installation_date = '{sample_rows[0]['installation_date']}'")
    try:
        for row in sample_rows:
            if row["installation_date"] is not None:
                assert re.match(r"^\d{4}-\d{2}-\d{2}$", row["installation_date"]), \
                    f"installation_date לא בפורמט תקין בשורה {row['row_number']} (ערך: {row['installation_date']})"
        report("installation_date בפורמט YYYY-MM-DD", True)
    except AssertionError as e:
        report("installation_date בפורמט YYYY-MM-DD", False, str(e))

#  3. SPECIFIC VALUES : first row check

def test_first_row_values():
    """ערכי שורה ראשונה תואמים את הנתונים בקובץ"""
    row = sample_rows[0]
    try:
        assert row["row_number"] == 1, f"row_number={row['row_number']} (צפוי 1)"
        assert row["meter_number"] == "706D7E805DA846A3", f"meter_number={row['meter_number']}"
        assert row["customer_number"] == "20433218196", f"customer_number={row['customer_number']}"
        assert row["address"] == "ויצמן 14", f"address={row['address']}"
        assert row["walk_order"] == 105035029, f"walk_order={row['walk_order']}"
        assert abs(row["previous_reading"] - 147.437) < 0.001, f"previous_reading={row['previous_reading']}"
        assert row["installation_date"] == "2024-12-10", f"installation_date={row['installation_date']}"
        report("ערכי שורה ראשונה תואמים לקובץ", True)
    except AssertionError as e:
        report("ערכי שורה ראשונה", False, str(e))

#  4. VALIDATION

def test_valid_rows_pass():
    """שורות תקינות עוברות ולידציה בלי שגיאות"""
    errors = parser.validate_all_rows(sample_rows)
    try:
        assert len(errors) == 0
        report(f"ולידציה על קובץ דוגמה → {len(errors)} שגיאות (צפוי 0)", True)
    except AssertionError as e:
        report(f"ולידציה על קובץ דוגמה → {len(errors)} שגיאות (צפוי 0)", False, str(e))

def test_missing_meter_number():
    """מספר מונה חסר מזוהה"""
    row = {"row_number": 1, "meter_number": None}
    errors = parser.validate_row(row, 1)
    try:
        assert any("מספר מונה" in e for e in errors)
        report("מספר מונה חסר → שגיאה", True)
    except AssertionError as e:
        report("מספר מונה חסר → שגיאה", False, str(e))

def test_empty_meter_number():
    """מספר מונה ריק מזוהה"""
    row = {"row_number": 1, "meter_number": ""}
    errors = parser.validate_row(row, 1)
    try:
        assert any("ריק" in e for e in errors)
        report("מספר מונה ריק → שגיאה", True)
    except AssertionError as e:
        report("מספר מונה ריק → שגיאה", False, str(e))

def test_negative_reading():
    row = {"row_number": 1, "meter_number": "ABC", "previous_reading": -5.0}
    errors = parser.validate_row(row, 1)
    try:
        assert any("שלילית" in e for e in errors)
        report("קריאה קודמת שלילית → שגיאה", True)
    except AssertionError as e:
        report("קריאה קודמת שלילית → שגיאה", False, str(e))

#  5. ERROR HANDLING : bad files

def test_file_not_found():
    """קובץ לא קיים זורק שגיאה"""
    try:
        parser.parse("nonexistent_file.xlsx")
        report("קובץ לא קיים", False, "לא נזרקה שגיאה")
    except FileNotFoundError:
        report("קובץ לא קיים → FileNotFoundError", True)

def test_empty_file():
    """קובץ ריק זורק שגיאה"""
    try:
        parser.parse(EMPTY_FILE)
        report("קובץ ריק", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "ריק" in str(e)
            report(f"קובץ ריק → ValueError ('{e}')", True)
        except AssertionError as ae:
            report(f"קובץ ריק → ValueError ('{e}')", False, str(ae))

def test_header_only():
    """קובץ עם כותרת בלבד זורק שגיאה"""
    try:
        parser.parse(HEADER_ONLY_FILE)
        report("קובץ בלי נתונים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "שורות נתונים" in str(e)
            report(f"קובץ בלי נתונים → ValueError ('{e}')", True)
        except AssertionError as ae:
            report(f"קובץ בלי נתונים → ValueError ('{e}')", False, str(ae))

def test_wrong_headers():
    """קובץ עם כותרות לא נכונות זורק שגיאה"""
    try:
        parser.parse(WRONG_HEADERS_FILE)
        report("כותרות לא נכונות", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "עמודות" in str(e) or "כותרת" in str(e)
            report(f"כותרות לא נכונות → ValueError ('{e}')", True)
        except AssertionError as ae:
            report(f"כותרות לא נכונות → ValueError ('{e}')", False, str(ae))

#  6. #N/A HANDLING

def create_na_test_file():
    """Create a temp file with #N/A values for testing"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["מס'ד", "מס' זיהוי", "מספר מונה", "מספר משדר", "נוכחית", "כתובת", "סדר הליכה ", "מודל", "קוטר", "תאריך התקנה", "קו אורך", "קו רוחב"])
    ws.append([1, 12345, "METER001", "METER001", "#N/A", "רחוב 1", 100, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    ws.append([2, 67890, "METER002", "METER002", 150.5, "רחוב 2", None, "מודל", '0.75"', datetime(2024, 1, 1), 34.87, 32.34])
    wb.save(NA_FILE)


def cleanup_na_file():
    if os.path.exists(NA_FILE):
        os.remove(NA_FILE)

def test_na_becomes_none():
    """#N/A בקריאה קודמת הופך ל-None"""
    rows = parser.parse(NA_FILE)
    print(f"    שורה 1: previous_reading = {rows[0]['previous_reading']} (צפוי None)")
    try:
        assert rows[0]["previous_reading"] is None
        report("#N/A → None", True)
    except AssertionError as e:
        report("#N/A → None", False, str(e))

def test_row_after_na_valid():
    """שורה תקינה אחרי שורת #N/A עדיין עובדת"""
    rows = parser.parse(NA_FILE)
    print(f"    שורה 2: previous_reading = {rows[1]['previous_reading']} (צפוי 150.5)")
    try:
        assert abs(rows[1]["previous_reading"] - 150.5) < 0.001
        report("שורה אחרי #N/A תקינה", True)
    except AssertionError as e:
        report("שורה אחרי #N/A תקינה", False, str(e))


#  RUN ALL TESTS

def main():
    print("=" * 55)
    print("  Monim : Netanya Parser Tests")
    print("=" * 55)

    try: 
        # Setup
        print("\n=== הכנה ===")
        setup()

        # 1. Basics
        print("=== בדיקות בסיס ===")
        test_inherits_from_base_parser()
        test_file_type()
        test_parse_row_count()

        # 2. Normalization
        print("\n=== בדיקות נרמול : טיפוסים ומבנה ===")
        test_row_structure()
        test_walk_order_and_reading_types()
        test_installation_date_format()

        # 3. Specific values
        print("\n=== בדיקות ערכים ספציפיים ===")
        test_first_row_values()

        # 4. Validation
        print("\n=== בדיקות ולידציה ===")
        test_valid_rows_pass()
        test_missing_meter_number()
        test_empty_meter_number()
        test_negative_reading()

        # 5. Error handling
        print("\n=== בדיקות טיפול בקבצים שגויים ===")
        test_file_not_found()
        test_empty_file()
        test_header_only()
        test_wrong_headers()

        # 6. #N/A
        print("\n=== בדיקות ערכי #N/A ===")
        create_na_test_file()
        test_na_becomes_none()
        test_row_after_na_valid()
        cleanup_na_file()

    finally: 
        # Summary
        print("\n" + "=" * 55)
        print_summary()
        print("=" * 55)


if __name__ == "__main__":
    main()