"""
Monim - Shared Consumption Tests
Testing SharedConsumptionService: the grouping logic, the shared-consumption
formula, and the full calculate() flow (including DB writes).

Tests Summary:

1. _calculate_group - Pure Formula (6 tests)
   - Basic calculation
   - No apartments -> None
   - Main meter has no consumption -> None
   - Negative result returned as-is (not None, not 0)
   - Apartments with no reading counted as 0 in the sum (current behavior,
     may change per manager decision - see BEHAVIORS #C2)
   - Rounding to 3 decimal places

2. _build_groups - Grouping Logic (6 tests)
   - Basic grouping by meter_id prefix
   - Same address, different meter_id prefix -> separate buildings
   - Orphan apartment (no matching main meter) excluded
   - Main meter without apartments filtered out
   - meter_id shorter than 8 digits skipped
   - Duplicate main meter for same building -> first one wins

3. calculate() - Full Integration (with DB) (5 tests)
   - Shared consumption saved to all apartments
   - Negative shared consumption marks main meter as exception
   - Exception self-heals on recalculate once consumption is valid again
     (regression coverage for the fragile manager_notes string-match logic)
   - Building with no reading on main meter is skipped
   - shared_consumption reset to NULL before recalculating

Run: python -m tests.services_tests.test_shared_consumption

Total: 17 tests
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from tests.test_helpers import report, print_summary, reset_counters
from src.services.shared_consumption_service import SharedConsumptionService
from tests.test_helpers import report, print_summary, reset_counters, cleanup
from src.services.client_service import ClientService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from src.services.reader_service import ReaderService
from src.services.reading_service import ReadingService

client_service = ClientService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
reader_service = ReaderService()
reading_service = ReadingService()


svc = SharedConsumptionService()


def _make_group(main_consumption, apartment_consumptions):
    """עוזר: בונה group תקין מתוך צריכת כללי ורשימת צריכות דירות."""
    return {
        'main_meter': {'consumption': main_consumption},
        'apartments': [{'consumption': c} for c in apartment_consumptions],
    }

# HELPERS
def _setup_period_and_reader(suffix):
    """
    Test helper: creates a fresh client, period, source file, and reader', the minimal setup needed before building a test "building" 
    (main meter + apartments) for a shared-consumption calculate() test.

    Returns: (period, source_file, reader) the created records
    """
    client = client_service.create_client(
        name=f"לקוח בדיקה - צריכה משותפת {suffix}",
        corporation_number=f"9990001{suffix:02d}")
    period = period_service.create_period(
        client['client_id'], 2026, 1)
    sf = source_file_service.upload_period_file(
        period_id=period['period_id'], original_filename="test_shared.xlsx", file_type="excel")
    reader = reader_service.create_reader(
        name=f"קורא בדיקה {suffix}", username=f"sc_test_reader_{suffix}", password_hash="hash")
    return period, sf, reader

def _create_building(period_id, source_file_id, prefix, main_previous, apt_previous_list):
    """
    Test helper: creates one "building", a main meter (usage_type='1') plus N apartment meters (usage_type='5') sharing the same building_key prefix,
    ready for SharedConsumptionService to group and calculate.

    Returns: (main_meter_dict, [apartment_dicts]) freshly fetched from the DB after creation, so callers see real period_meter_id values
    """
    rows = [{
        'row_number': 1,
        'meter_number': f'{prefix}-MAIN',
        'previous_reading': main_previous,
        'raw_data': {'meter_id': f'{prefix}001', 'usage_type': '1'},
    }]
    for i, prev in enumerate(apt_previous_list, start=1):
        rows.append({
            'row_number': i + 1,
            'meter_number': f'{prefix}-APT{i}',
            'previous_reading': prev,
            'raw_data': {'meter_id': f'{prefix}{i:03d}', 'usage_type': '5'},
        })
    meter_service.create_meters_from_parsed_rows(period_id, source_file_id, rows)

    all_meters = meter_service.get_period_meters(period_id)
    main = next(m for m in all_meters if m['meter_number'] == f'{prefix}-MAIN')
    apartments = [m for m in all_meters if m['meter_number'].startswith(f'{prefix}-APT')]
    return main, apartments

# 1. CALCULATE_GROUP : pure formula, no DB

def test_basic_calculation():
    """C1: (500 - (20+30+50)) / 3 = 133.333"""
    try:
        group = _make_group(500, [20, 30, 50])
        result = svc._calculate_group(group)
        assert result == 133.333, f"ציפינו 133.333, קיבלנו {result}"
        report("C1 - חישוב בסיסי", True)
    except AssertionError as e:
        report("C1 - חישוב בסיסי", False, str(e))

def test_no_apartments():
    """C3: בניין בלי דירות → None"""
    try:
        group = _make_group(500, [])
        result = svc._calculate_group(group)
        assert result is None, f"ציפינו None, קיבלנו {result}"
        report("C3 - אין דירות → None", True)
    except AssertionError as e:
        report("C3 - אין דירות → None", False, str(e))

def test_main_no_consumption():
    """C4: מונה כללי בלי צריכה → None"""
    try:
        group = _make_group(None, [20, 30, 50])
        result = svc._calculate_group(group)
        assert result is None, f"ציפינו None, קיבלנו {result}"
        report("C4 - כללי בלי צריכה → None", True)
    except AssertionError as e:
        report("C4 - כללי בלי צריכה → None", False, str(e))

def test_negative_result():
    """C5: סכום דירות > צריכת כללי → תוצאה שלילית (לא None, לא 0)"""
    try:
        group = _make_group(300, [200, 150, 50])  # סכום 400 > 300
        result = svc._calculate_group(group)
        assert result == round((300 - 400) / 3, 3), f"ציפינו שלילי, קיבלנו {result}"
        assert result < 0, f"התוצאה צריכה להיות שלילית, קיבלנו {result}"
        report("C5 - תוצאה שלילית מוחזרת כמו שהיא", True)
    except AssertionError as e:
        report("C5 - תוצאה שלילית מוחזרת כמו שהיא", False, str(e))

def test_partial_reading_current_behavior():
    """
    C2: דירות ללא קריאה נספרות כ-0 בסכום, אך כן במחלק.
    כללי 500, 5 דירות עם קריאה (סכום 240), 8 דירות ללא קריאה (None).
    (500 - 240) / 13 = 20.0

    ⚠ התנהגות זו עשויה להשתנות לפי החלטת מנהל העבודה (ראה BEHAVIORS #C2).
    """
    try:
        group = _make_group(500, [50, 30, 60, 20, 80] + [None] * 8)
        result = svc._calculate_group(group)
        assert result == 20.0, f"ציפינו 20.0, קיבלנו {result}"
        report("C2 - חישוב חלקי (התנהגות נוכחית)", True)
    except AssertionError as e:
        report("C2 - חישוב חלקי (התנהגות נוכחית)", False, str(e))

def test_rounding():
    """C6: (500-400)/13 = 7.6923... → מעוגל ל-7.692"""
    """C6: (500-400)/13 = 7.6923... → מעוגל ל-7.692"""
    try:
        group = _make_group(500, [30] * 12 + [40])  # סכום 400, 13 דירות
        result = svc._calculate_group(group)
        assert result == 7.692, f"ציפינו 7.692, קיבלנו {result}"
        report("C6 - עיגול ל-3 ספרות", True)
    except AssertionError as e:
        report("C6 - עיגול ל-3 ספרות", False, str(e))

# 2. BUILD_GROUPS : grouping logic, no DB

def test_build_groups_basic_grouping():
    """G1: מונה כללי + דירות עם אותה קידומת meter_id → קבוצה אחת"""
    try:
        meters = [
            {'meter_number': 'M1', 'address': 'ביאליק 6', 'raw_data': {'meter_id': '10500060001', 'usage_type': '1'}},
            {'meter_number': 'M2', 'address': 'ביאליק 6/1', 'raw_data': {'meter_id': '10500060002', 'usage_type': '5'}},
            {'meter_number': 'M3', 'address': 'ביאליק 6/2', 'raw_data': {'meter_id': '10500060003', 'usage_type': '5'}},
        ]
        groups = svc._build_groups(meters)
        assert len(groups) == 1
        assert groups[0]['building_key'] == '10500060'
        assert groups[0]['main_meter']['meter_number'] == 'M1'
        assert len(groups[0]['apartments']) == 2
        report("G1: קיבוץ בסיסי לפי meter_id", True)
    except AssertionError as e:
        report("G1: קיבוץ בסיסי לפי meter_id", False, str(e))

def test_build_groups_separates_by_meter_id_not_address():
    """G2: אותה כתובת, קידומת meter_id שונה → שני בניינים נפרדים"""
    try:
        meters = [
            {'meter_number': 'MAIN-A', 'address': 'הרצל 32', 'raw_data': {'meter_id': '20500320001', 'usage_type': '1'}},
            {'meter_number': 'APT-A1', 'address': 'הרצל 32', 'raw_data': {'meter_id': '20500320002', 'usage_type': '5'}},
            {'meter_number': 'MAIN-B', 'address': 'הרצל 32', 'raw_data': {'meter_id': '20500321001', 'usage_type': '1'}},
            {'meter_number': 'APT-B1', 'address': 'הרצל 32', 'raw_data': {'meter_id': '20500321002', 'usage_type': '5'}},
        ]
        groups = svc._build_groups(meters)
        keys = {g['building_key'] for g in groups}
        assert len(groups) == 2
        assert keys == {'20500320', '20500321'}
        report("G2: הפרדה לפי meter_id למרות כתובת זהה", True)
    except AssertionError as e:
        report("G2: הפרדה לפי meter_id למרות כתובת זהה", False, str(e))

def test_build_groups_orphan_apartment_excluded():
    """G3: דירה בלי מונה כללי תואם → לא נכנסת לשום קבוצה"""
    try:
        meters = [ {'meter_number': 'ORPHAN', 'address': 'שדרות ירושלים 10', 'raw_data': {'meter_id': '30509990001', 'usage_type': '5'}},]
        groups = svc._build_groups(meters)
        assert groups == []
        report("G3: דירה יתומה לא נכנסת לקבוצה", True)
    except AssertionError as e:
        report("G3: דירה יתומה לא נכנסת לקבוצה", False, str(e))

def test_build_groups_main_without_apartments_filtered():
    """G4: מונה כללי בלי דירות תואמות → מסונן החוצה"""
    try:
        meters = [{'meter_number': 'MAIN-ALONE', 'address': 'גן ציבורי', 'raw_data': {'meter_id': '40500060001', 'usage_type': '1'}}, ]
        groups = svc._build_groups(meters)
        assert groups == []
        report("G4: מונה כללי ללא דירות מסונן", True)
    except AssertionError as e:
        report("G4: מונה כללי ללא דירות מסונן", False, str(e))

def test_build_groups_short_meter_id_skipped():
    """G5: meter_id קצר מ-8 ספרות → מדולג, לא נכנס כבניין"""
    try:
        meters = [
            {'meter_number': 'SHORT-ID', 'address': 'לא ידוע', 'raw_data': {'meter_id': '1234567', 'usage_type': '1'}},  # 7 ספרות
            {'meter_number': 'APT-X', 'address': 'לא ידוע', 'raw_data': {'meter_id': '12345670001', 'usage_type': '5'}},
        ]
        groups = svc._build_groups(meters)
        assert groups == []
        report("G5: meter_id קצר מ-8 מדולג", True)
    except AssertionError as e:
        report("G5: meter_id קצר מ-8 מדולג", False, str(e))

def test_build_groups_duplicate_main_first_wins():
    """G6: שני מונים כלליים לאותה קידומת → הראשון נשמר, השני מדולג"""
    try:
        meters = [
            {'meter_number': 'MAIN-FIRST', 'address': 'ויצמן 6', 'raw_data': {'meter_id': '60500060001', 'usage_type': '1'}},
            {'meter_number': 'MAIN-SECOND', 'address': 'ויצמן 6', 'raw_data': {'meter_id': '60500060002', 'usage_type': '1'}},
            {'meter_number': 'APT-1', 'address': 'ויצמן 6/1', 'raw_data': {'meter_id': '60500060003', 'usage_type': '5'}},
        ]
        groups = svc._build_groups(meters)
        assert len(groups) == 1
        assert groups[0]['main_meter']['meter_number'] == 'MAIN-FIRST'
        report("G6: מונה כללי כפול - הראשון נשמר", True)
    except AssertionError as e:
        report("G6: מונה כללי כפול - הראשון נשמר", False, str(e))

# 3. CALCULATE : full integration, with DB

def test_shared_consumption_saved_to_apartments():
    """F1: בניין תקין - כל הדירות מקבלות את הצריכה המשותפת"""
    try:
        period, sf, reader = _setup_period_and_reader(1)
        main, apartments = _create_building(
            period['period_id'], sf['source_file_id'], '70500060',
            main_previous=0, apt_previous_list=[0, 0, 0])

        reading_service.create_reading(
            period_meter_id=main['period_meter_id'], reader_id=reader['reader_id'], current_reading=500)
        for apt, curr in zip(apartments, [20, 30, 50]):
            reading_service.create_reading(
                period_meter_id=apt['period_meter_id'], reader_id=reader['reader_id'], current_reading=curr)

        svc.calculate(period['period_id'])

        updated = meter_service.get_period_meters(period['period_id'])
        updated_apts = [m for m in updated if m['meter_number'].startswith('70500060-APT')]
        expected = round((500 - 100) / 3, 3)
        assert all(float(a['shared_consumption']) == expected for a in updated_apts), \
        f"ציפינו {expected} לכולם, קיבלנו {[a['shared_consumption'] for a in updated_apts]}"
        report("F1 - שמירת צריכה משותפת על כל הדירות", True)
    except AssertionError as e:
        report("F1 - שמירת צריכה משותפת על כל הדירות", False, str(e))

def test_negative_shared_consumption_marks_exception():
    """F2: צריכה משותפת שלילית - כללי → exception + הערה, דירות נשארות NULL"""
    try:
        period, sf, reader = _setup_period_and_reader(2)
        main, apartments = _create_building(
            period['period_id'], sf['source_file_id'], '70500061',
            main_previous=0, apt_previous_list=[0, 0, 0])

        reading_service.create_reading(
            period_meter_id=main['period_meter_id'], reader_id=reader['reader_id'], current_reading=100)
        for apt, curr in zip(apartments, [150, 150, 100]):
            reading_service.create_reading(
                period_meter_id=apt['period_meter_id'], reader_id=reader['reader_id'], current_reading=curr)

        svc.calculate(period['period_id'])

        updated = meter_service.get_period_meters(period['period_id'])
        updated_main = next(m for m in updated if m['meter_number'] == '70500061-MAIN')
        updated_apts = [m for m in updated if m['meter_number'].startswith('70500061-APT')]

        assert updated_main['work_status'] == 'exception', \
            f"ציפינו exception, קיבלנו {updated_main['work_status']}"
        assert updated_main['manager_notes'] and 'צריכה משותפת שלילית' in updated_main['manager_notes'], \
            f"ציפינו הערה על צריכה שלילית, קיבלנו: {updated_main['manager_notes']}"
        assert all(a['shared_consumption'] is None for a in updated_apts), \
            f"ציפינו NULL לכל הדירות, קיבלנו {[a['shared_consumption'] for a in updated_apts]}"
        report("F2 - צריכה שלילית → exception + דירות NULL", True)
    except AssertionError as e:
        report("F2 - צריכה שלילית → exception + דירות NULL", False, str(e))

def test_exception_self_heals_on_recalculate():
    """F5: exception שנוצר ע"י המערכת מתאפס אוטומטית כשהצריכה חוזרת להיות תקינה"""
    try:
        period, sf, reader = _setup_period_and_reader(5)
        main, apartments = _create_building(
            period['period_id'], sf['source_file_id'], '70500065',
            main_previous=0, apt_previous_list=[0, 0, 0])

        # ריצה ראשונה: צריכה שלילית → exception
        reading_service.create_reading(
            period_meter_id=main['period_meter_id'], reader_id=reader['reader_id'], current_reading=100)
        for apt, curr in zip(apartments, [150, 150, 100]):
            reading_service.create_reading(
                period_meter_id=apt['period_meter_id'], reader_id=reader['reader_id'], current_reading=curr)

        svc.calculate(period['period_id'])

        after_first = meter_service.get_period_meters(period['period_id'])
        main_after_first = next(m for m in after_first if m['meter_number'] == '70500065-MAIN')
        assert main_after_first['work_status'] == 'exception', \
            f"ציפינו exception אחרי ריצה ראשונה, קיבלנו {main_after_first['work_status']}"

        # מתקנים את הקריאה של הכללי כך שהצריכה תהיה חיובית
        reading_service.create_reading(
            period_meter_id=main['period_meter_id'], reader_id=reader['reader_id'], current_reading=600)

        # ריצה שנייה: הצריכה כעת תקינה - ה-exception אמור להתאפס
        svc.calculate(period['period_id'])

        after_second = meter_service.get_period_meters(period['period_id'])
        main_after_second = next(m for m in after_second if m['meter_number'] == '70500065-MAIN')
        assert main_after_second['work_status'] == 'new', \
            f"ציפינו שה-exception יתאפס ל-new, קיבלנו {main_after_second['work_status']}"

        updated_apts = [m for m in after_second if m['meter_number'].startswith('70500065-APT')]
        expected = round((600 - 400) / 3, 3)
        assert all(float(a['shared_consumption']) == expected for a in updated_apts), \
            f"ציפינו {expected} לדירות אחרי ריצה שנייה, קיבלנו {[a['shared_consumption'] for a in updated_apts]}"

        report("F5 - exception מתאפס אוטומטית כשהצריכה תקינה", True)
    except AssertionError as e:
        report("F5 - exception מתאפס אוטומטית כשהצריכה תקינה", False, str(e))

def test_building_without_readings_is_skipped():
    """F3: כללי בלי consumption (אין קריאת שדה) → נספר ב-skipped, דירות לא משתנות"""
    try:
        period, sf, reader = _setup_period_and_reader(3)
        main, apartments = _create_building(
            period['period_id'], sf['source_file_id'], '70500063',
            main_previous=0, apt_previous_list=[0, 0, 0])

        for apt, curr in zip(apartments, [20, 30, 50]):
            reading_service.create_reading(
                period_meter_id=apt['period_meter_id'], reader_id=reader['reader_id'], current_reading=curr)

        result = svc.calculate(period['period_id'])

        assert result['skipped'] == 1, f"ציפינו skipped=1, קיבלנו {result['skipped']}"

        updated = meter_service.get_period_meters(period['period_id'])
        updated_apts = [m for m in updated if m['meter_number'].startswith('70500063-APT')]
        assert all(a['shared_consumption'] is None for a in updated_apts), \
            f"ציפינו NULL (לא השתנו), קיבלנו {[a['shared_consumption'] for a in updated_apts]}"
        report("F3 - בניין בלי consumption בכללי → skipped", True)
    except AssertionError as e:
        report("F3 - בניין בלי consumption בכללי → skipped", False, str(e))

def test_shared_consumption_reset_before_recalculate():
    """F4: בניין שכבר חושב → shared_consumption מתאפס ל-NULL לפני חישוב מחדש"""
    try:
        period, sf, reader = _setup_period_and_reader(4)
        main, apartments = _create_building(
            period['period_id'], sf['source_file_id'], '70500064',
            main_previous=0, apt_previous_list=[0, 0, 0])

        reading_service.create_reading(
            period_meter_id=main['period_meter_id'], reader_id=reader['reader_id'], current_reading=500)
        for apt, curr in zip(apartments, [20, 30, 50]):
            reading_service.create_reading(
                period_meter_id=apt['period_meter_id'], reader_id=reader['reader_id'], current_reading=curr)

        svc.calculate(period['period_id'])

        updated = meter_service.get_period_meters(period['period_id'])
        updated_apts = [m for m in updated if m['meter_number'].startswith('70500064-APT')]
        first_value = updated_apts[0]['shared_consumption']
        assert first_value is not None, "ציפינו ערך אחרי ריצה ראשונה"

        meter_repo = meter_service.repo
        meter_repo.db.execute_query(
            "UPDATE period_meters SET consumption = NULL WHERE period_meter_id = %s",
            (main['period_meter_id'],), commit=True)

        result2 = svc.calculate(period['period_id'])

        assert result2['skipped'] == 1, f"ציפינו skipped=1 בריצה השנייה, קיבלנו {result2}"

        updated2 = meter_service.get_period_meters(period['period_id'])
        updated_apts2 = [m for m in updated2 if m['meter_number'].startswith('70500064-APT')]
        assert all(a['shared_consumption'] is None for a in updated_apts2), \
            f"ציפינו איפוס ל-NULL, קיבלנו {[a['shared_consumption'] for a in updated_apts2]}"
        report("F4 - איפוס לפני חישוב מחדש", True)
    except AssertionError as e:
        report("F4 - איפוס לפני חישוב מחדש", False, str(e))

def main():
    reset_counters()
    print("=" * 50)
    print("  Monim tests : Shared Consumption Tests")
    print("=" * 50)

    try:
        print("\n=== 1. CALCULATE_GROUP : pure formula, no DB ===")
        test_basic_calculation()
        test_no_apartments()
        test_main_no_consumption()
        test_negative_result()
        test_partial_reading_current_behavior()  # התנהגות שאולי תשתנה בעתיד
        test_rounding()

        print("\n=== 2. BUILD_GROUPS : grouping logic, no DB ===")
        test_build_groups_basic_grouping()
        test_build_groups_separates_by_meter_id_not_address()
        test_build_groups_orphan_apartment_excluded()
        test_build_groups_main_without_apartments_filtered()
        test_build_groups_short_meter_id_skipped()
        test_build_groups_duplicate_main_first_wins()

        print("\n=== 3. CALCULATE : full integration, with DB ===")
        cleanup()
        test_shared_consumption_saved_to_apartments()
        test_negative_shared_consumption_marks_exception()
        test_exception_self_heals_on_recalculate()
        test_building_without_readings_is_skipped()
        test_shared_consumption_reset_before_recalculate()

        print_summary()

    finally:
        cleanup()



if __name__ == "__main__":
    main()