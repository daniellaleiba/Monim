"""
Monim - DOS Parser Tests
Testing parsing, normalization, RTL decoding, and error handling for NetanyaDParser
(fixed-width DOS cp862 format, used by מי נתניה and similar corporations).
 
Note: These tests work on files only - no DB access needed.
 
Fixture: dos_sample.D is 10 real rows sampled evenly from an actual production .D file. 
Personally-identifying fields (customer name, address, customer number, meter number, physical_number, meter_id) are redacted (replaced with 'X'). 
All operational fields (walk_order, readings, dates, usage_type) are real, unmodified data - see script _generate_dos_sample.py for how this fixture was built.
 
Because identifying fields are redacted to repeated 'X' characters, RTL reversal, walk_order fallback, and file-level error handling
cannot be verified through dos_sample.D (a redacted field looks the same reversed or not). 
Those cases are tested with small, synthetic, fully-fabricated byte rows built inline in this file instead.
 
Tests Summary:
 
1. Basic Parsing (3 tests)
   - Parser inherits from BaseParser
   - file_type returns 'netanya_d_format'
   - Sample file parsed correctly (10 rows)
 
2. RTL / Hebrew Decoding (2 tests)
   - _fix_hebrew reverses text back to readable form
   - Digit runs inside reversed text are preserved in correct order
 
3. Fixed-Width Extraction (2 tests)
   - Known real values from dos_sample.D match expected offsets
   - previous_reading matches hist_readings[0] (same source field)
 
4. Walk Order Fallback (2 tests)
   - Primary walk_order field used when present
   - Falls back to alternate field when primary is blank/zero
 
5. Dates (4 tests)
   - installation_date across sample rows all match YYYY-MM-DD
   - '00/00/0000' becomes None
   - year '1900' becomes None
   - reception_date '000000' (YYMMDD) becomes None
 
6. Historical Data (2 tests)
   - hist_readings has 7 entries (current + 6 periods)
   - hist_diffs has 6 entries
 
7. File-Level Error Handling (3 tests)
   - File not found raises FileNotFoundError
   - Empty file raises ValueError
   - File with no valid-length rows raises ValueError
 
8. Row Filtering (2 tests)
   - Row shorter than MIN_ROW_LENGTH is skipped
   - Row with blank meter_number is skipped
 
9. Validation (2 tests)
   - Valid rows (from dos_sample.D) pass validation with 0 errors
   - Negative previous_reading is detected
 
Total: 22 tests
"""
 
import sys
import os
 
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
 
from src.parsers.base_parser import BaseParser
from src.parsers.netanya_d_parser import NetanyaDParser
from tests.test_helpers import report, print_summary
 
# --- Test file path ---
TEST_DIR = os.path.dirname(__file__)
SAMPLE_FILE = os.path.join(TEST_DIR, "test_data", "dos_sample.D")
 
# --- Shared state ---
parser = NetanyaDParser()
sample_rows = None
 
 
def setup():
    """Parse sample file once for all tests"""
    global sample_rows
    sample_rows = parser.parse(SAMPLE_FILE)
    print(f"  Setup: נטען קובץ דוגמה עם {len(sample_rows)} שורות")
 
 
# --- Inline helpers for building synthetic fixed-width rows ---
# (used only for RTL / fallback / error / filtering tests - never for
#  the main sample, since those need fully fabricated, non-real data)
 
def _place(chars, text, start, end):
    text = str(text)[:end - start]
    for i, ch in enumerate(text):
        chars[start + i] = ch
 
 
def _build_line(walk_order="1000000000", walk_order_alt="", customer_number="12345678",
                 current_reading="0000100.5", installation_date="15/03/2020",
                 hist=None, meter_number="TESTMTR1", usage_type="5",
                 reception_date="", install_date_alt=""):
    """Builds one synthetic 503-char fixed-width row. All values fabricated."""
    if hist is None:
        hist = ["0000090.0", "0000080.0", "0000070.0", "0000060.0", "0000050.0", "0000040.0"]
    chars = [' '] * 503
    _place(chars, walk_order_alt, 9, 20)
    _place(chars, walk_order, 86, 96)
    _place(chars, customer_number, 102, 111)
    _place(chars, current_reading, 185, 195)
    for i, val in enumerate(hist):
        s, e = 195 + i * 10, 205 + i * 10
        _place(chars, val, s, e)
    if usage_type:
        chars[169] = usage_type[0]
    _place(chars, reception_date, 179, 185)
    _place(chars, install_date_alt, 141, 147)
    _place(chars, installation_date, 272, 282)
    _place(chars, meter_number, 495, 503)
    return "".join(chars)
 
 
def _write_temp_dos_file(path, lines):
    with open(path, "wb") as f:
        f.write(b"\r\n".join(l.encode("cp862") for l in lines))
 
TEMP_FILE = os.path.join(TEST_DIR, "test_data", "dos_temp_case.D")
 
def cleanup_temp_file():
    if os.path.exists(TEMP_FILE):
        os.remove(TEMP_FILE)
 
#  1. BASIC PARSING
 
def test_inherits_from_base_parser():
    """Parser יורש מ-BaseParser"""
    try:
        assert isinstance(parser, BaseParser)
        report("Parser יורש מ-BaseParser", True)
    except AssertionError as e:
        report("Parser יורש מ-BaseParser", False, str(e))
 
def test_file_type():
    """file_type מחזיר netanya_d_format"""
    try:
        assert parser.get_file_type() == "netanya_d_format"
        report("file_type = 'netanya_d_format'", True)
    except AssertionError as e:
        report("file_type = 'netanya_d_format'", False, str(e))
 
def test_parse_row_count():
    """קובץ דוגמה מחזיר 10 שורות"""
    try:
        assert len(sample_rows) == 10
        report(f"קובץ דוגמה → {len(sample_rows)} שורות (צפוי 10)", True)
    except AssertionError as e:
        report(f"קובץ דוגמה → {len(sample_rows)} שורות (צפוי 10)", False, str(e))
 
#  2. RTL / HEBREW DECODING
 
def test_fix_hebrew_reverses_text():
    """_fix_hebrew הופך טקסט הפוך לקריא"""
    # "ZYX123CBA" is the hand-derived DOS-reversed encoding of "ABC123XYZ"
    # (whole-string reverse + digit-run re-reverse - see class docstring)
    raw = "ZYX123CBA"
    expected = "ABC123XYZ"
    try:
        result = parser._fix_hebrew(raw)
        assert result == expected, f"קיבל '{result}', צפוי '{expected}'"
        report("_fix_hebrew הופך טקסט לקריא", True)
    except AssertionError as e:
        report("_fix_hebrew הופך טקסט לקריא", False, str(e))
 
def test_fix_hebrew_preserves_digit_order():
    """מספרים בתוך טקסט הפוך נשארים בסדר הנכון (לא הופכים שוב)"""
    raw = "ZYX123CBA"
    try:
        result = parser._fix_hebrew(raw)
        assert "123" in result, f"הציפייה ש-'123' יופיע ברצף נכון בתוך '{result}'"
        report("רצפי ספרות נשמרים בכיוון נכון", True)
    except AssertionError as e:
        report("רצפי ספרות נשמרים בכיוון נכון", False, str(e))
 
#  3. FIXED-WIDTH EXTRACTION : real values from dos_sample.D
 
def test_known_row_values():
    """ערכים אמיתיים משורה 0 בקובץ הדוגמה תואמים למצופה"""
    row = sample_rows[0]
    try:
        assert row["walk_order"] == 1111338000, f"walk_order={row['walk_order']}"
        assert abs(row["previous_reading"] - 0.3) < 0.001, f"previous_reading={row['previous_reading']}"
        assert row["installation_date"] == "1990-01-01", f"installation_date={row['installation_date']}"
        assert row["raw_data"]["usage_type"] == "1", f"usage_type={row['raw_data']['usage_type']}"
        report("ערכי שורה 0 תואמים לקובץ הדוגמה", True)
    except AssertionError as e:
        report("ערכי שורה 0 תואמים לקובץ הדוגמה", False, str(e))
 
def test_previous_reading_matches_hist_current():
    """previous_reading זהה לערך הראשון ב-hist_readings (אותו שדה מקור)"""
    try:
        for row in sample_rows:
            hist = row["raw_data"]["hist_readings"]
            assert hist[0] == row["previous_reading"], \
                f"שורה {row['row_number']}: hist[0]={hist[0]} != previous_reading={row['previous_reading']}"
        report("previous_reading תואם ל-hist_readings[0] בכל השורות", True)
    except AssertionError as e:
        report("previous_reading תואם ל-hist_readings[0] בכל השורות", False, str(e))
 
#  4. WALK ORDER FALLBACK
 
def test_walk_order_primary_used():
    """כאשר השדה הראשי מלא - הוא זה שמשמש"""
    line = _build_line(walk_order="1234567890", walk_order_alt="9999999999")
    _write_temp_dos_file(TEMP_FILE, [line])
    try:
        rows = parser.parse(TEMP_FILE)
        assert rows[0]["walk_order"] == 1234567890, f"walk_order={rows[0]['walk_order']}"
        report("walk_order: שדה ראשי בשימוש כשמלא", True)
    except AssertionError as e:
        report("walk_order: שדה ראשי בשימוש כשמלא", False, str(e))
    finally:
        cleanup_temp_file()
 
def test_walk_order_fallback_when_primary_blank():
    """כאשר השדה הראשי ריק - נופל לשדה החלופי"""
    line = _build_line(walk_order="", walk_order_alt="7654321")
    _write_temp_dos_file(TEMP_FILE, [line])
    try:
        rows = parser.parse(TEMP_FILE)
        assert rows[0]["walk_order"] == 7654321, f"walk_order={rows[0]['walk_order']}"
        report("walk_order: נופל לשדה חלופי כשראשי ריק", True)
    except AssertionError as e:
        report("walk_order: נופל לשדה חלופי כשראשי ריק", False, str(e))
    finally:
        cleanup_temp_file()
 
#  5. DATES
 
def test_installation_dates_valid_format():
    """כל תאריכי ההתקנה בקובץ הדוגמה בפורמט YYYY-MM-DD"""
    import re
    try:
        for row in sample_rows:
            d = row["installation_date"]
            if d is not None:
                assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"שורה {row['row_number']}: תאריך '{d}' לא בפורמט תקין"
        report("כל תאריכי ההתקנה בפורמט YYYY-MM-DD", True)
    except AssertionError as e:
        report("כל תאריכי ההתקנה בפורמט YYYY-MM-DD", False, str(e))
 
def test_zero_date_becomes_none():
    """תאריך '00/00/0000' הופך ל-None"""
    try:
        result = parser._parse_date("00/00/0000")
        assert result is None, f"קיבל '{result}', צפוי None"
        report("'00/00/0000' → None", True)
    except AssertionError as e:
        report("'00/00/0000' → None", False, str(e))
 
def test_year_1900_becomes_none():
    """שנה '1900' נחשבת placeholder והופכת ל-None"""
    try:
        result = parser._parse_date("15/06/1900")
        assert result is None, f"קיבל '{result}', צפוי None"
        report("שנת 1900 → None (placeholder)", True)
    except AssertionError as e:
        report("שנת 1900 → None (placeholder)", False, str(e))
 
def test_yymmdd_zeros_becomes_none():
    """reception_date '000000' (YYMMDD) הופך ל-None"""
    try:
        result = parser._parse_yymmdd("000000")
        assert result is None, f"קיבל '{result}', צפוי None"
        report("YYMMDD '000000' → None", True)
    except AssertionError as e:
        report("YYMMDD '000000' → None", False, str(e))
 
#  6. HISTORICAL DATA
 
def test_hist_readings_length():
    """hist_readings מכיל 7 ערכים (נוכחי + 6 תקופות)"""
    try:
        for row in sample_rows:
            hist = row["raw_data"]["hist_readings"]
            assert len(hist) == 7, f"שורה {row['row_number']}: אורך hist_readings={len(hist)} (צפוי 7)"
        report("hist_readings: 7 ערכים בכל שורה", True)
    except AssertionError as e:
        report("hist_readings: 7 ערכים בכל שורה", False, str(e))
 
def test_hist_diffs_length():
    """hist_diffs מכיל 6 ערכים"""
    try:
        for row in sample_rows:
            diffs = row["raw_data"]["hist_diffs"]
            assert len(diffs) == 6, f"שורה {row['row_number']}: אורך hist_diffs={len(diffs)} (צפוי 6)"
        report("hist_diffs: 6 ערכים בכל שורה", True)
    except AssertionError as e:
        report("hist_diffs: 6 ערכים בכל שורה", False, str(e))
 
#  7. FILE-LEVEL ERROR HANDLING
 
def test_file_not_found():
    """קובץ לא קיים זורק שגיאה"""
    try:
        parser.parse("nonexistent_file.D")
        report("קובץ לא קיים", False, "לא נזרקה שגיאה")
    except FileNotFoundError:
        report("קובץ לא קיים → FileNotFoundError", True)
 
def test_empty_file():
    """קובץ ריק (0 בייטים) זורק שגיאה"""
    _write_temp_dos_file(TEMP_FILE, [])
    try:
        parser.parse(TEMP_FILE)
        report("קובץ ריק", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "ריק" in str(e)
            report(f"קובץ ריק → ValueError ('{e}')", True)
        except AssertionError as ae:
            report(f"קובץ ריק → ValueError ('{e}')", False, str(ae))
    finally:
        cleanup_temp_file()
 
def test_no_valid_length_rows():
    """קובץ עם שורות קצרות בלבד (אין אף שורה תקינה) זורק שגיאה"""
    _write_temp_dos_file(TEMP_FILE, ["too short", "also short"])
    try:
        parser.parse(TEMP_FILE)
        report("קובץ בלי שורות תקינות", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "שורות נתונים" in str(e)
            report(f"קובץ בלי שורות תקינות → ValueError ('{e}')", True)
        except AssertionError as ae:
            report(f"קובץ בלי שורות תקינות → ValueError ('{e}')", False, str(ae))
    finally:
        cleanup_temp_file()
 
#  8. ROW FILTERING
 
def test_short_row_skipped():
    """שורה קצרה מ-MIN_ROW_LENGTH מדולגת, שורה תקינה אחריה עדיין נקלטת"""
    valid_line = _build_line(meter_number="VALIDMTR")
    _write_temp_dos_file(TEMP_FILE, ["too short a line", valid_line])
    try:
        rows = parser.parse(TEMP_FILE)
        assert len(rows) == 1, f"מספר שורות={len(rows)} (צפוי 1, השורה הקצרה מדולגת)"
        assert rows[0]["meter_number"] == "VALIDMTR"
        report("שורה קצרה מדולגת, שורה תקינה נקלטת", True)
    except AssertionError as e:
        report("שורה קצרה מדולגת, שורה תקינה נקלטת", False, str(e))
    finally:
        cleanup_temp_file()
 
def test_blank_meter_number_skipped():
    """שורה עם meter_number ריק מדולגת"""
    blank_line = _build_line(meter_number="")
    valid_line = _build_line(meter_number="VALIDMTR")
    _write_temp_dos_file(TEMP_FILE, [blank_line, valid_line])
    try:
        rows = parser.parse(TEMP_FILE)
        assert len(rows) == 1, f"מספר שורות={len(rows)} (צפוי 1, השורה בלי מספר מונה מדולגת)"
        assert rows[0]["meter_number"] == "VALIDMTR"
        report("שורה עם meter_number ריק מדולגת", True)
    except AssertionError as e:
        report("שורה עם meter_number ריק מדולגת", False, str(e))
    finally:
        cleanup_temp_file()
 
#  9. VALIDATION
 
def test_valid_rows_pass():
    """שורות תקינות (מקובץ הדוגמה) עוברות ולידציה בלי שגיאות"""
    try:
        errors = parser.validate_all_rows(sample_rows)
        assert len(errors) == 0, f"נמצאו {len(errors)} שגיאות: {errors}"
        report(f"ולידציה על קובץ דוגמה → 0 שגיאות", True)
    except AssertionError as e:
        report(f"ולידציה על קובץ דוגמה → 0 שגיאות", False, str(e))
 
def test_negative_reading_detected():
    """קריאה קודמת שלילית מזוהה"""
    row = {"row_number": 1, "meter_number": "ABC", "previous_reading": -5.0, "raw_data": {}}
    try:
        errors = parser.validate_row(row, 1)
        assert any("שלילית" in e for e in errors)
        report("קריאה קודמת שלילית → שגיאה", True)
    except AssertionError as e:
        report("קריאה קודמת שלילית → שגיאה", False, str(e))
 
#  RUN ALL TESTS
 
def main():
    print("=" * 55)
    print("  Monim - DOS Parser Tests")
    print("=" * 55)
 
    try:
        print("\n=== הכנה ===")
        setup()
 
        print("\n=== בדיקות בסיס ")
        test_inherits_from_base_parser()
        test_file_type()
        test_parse_row_count()
 
        print("\n=== בדיקות פענוח RTL")
        test_fix_hebrew_reverses_text()
        test_fix_hebrew_preserves_digit_order()
 
        print("\n=== בדיקות שליפת שדות (fixed-width)")
        test_known_row_values()
        test_previous_reading_matches_hist_current()
 
        print("\n=== בדיקות walk_order fallback")
        test_walk_order_primary_used()
        test_walk_order_fallback_when_primary_blank()
 
        print("\n=== בדיקות תאריכים ")
        test_installation_dates_valid_format()
        test_zero_date_becomes_none()
        test_year_1900_becomes_none()
        test_yymmdd_zeros_becomes_none()
 
        print("\n=== בדיקות נתונים היסטוריים ")
        test_hist_readings_length()
        test_hist_diffs_length()
 
        print("\n=== בדיקות טיפול בקבצים שגויים ")
        test_file_not_found()
        test_empty_file()
        test_no_valid_length_rows()
 
        print("\n=== בדיקות סינון שורות ")
        test_short_row_skipped()
        test_blank_meter_number_skipped()
 
        print("\n=== בדיקות ולידציה ")
        test_valid_rows_pass()
        test_negative_reading_detected()
 
    finally:
        print("\n" + "=" * 55)
        print_summary()
        print("=" * 55)
 
 
if __name__ == "__main__":
    main()