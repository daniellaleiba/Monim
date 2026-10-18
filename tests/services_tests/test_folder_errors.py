"""
Monim : Folder Error Tests
Testing edge cases for FolderTemplate and WorkFolder entities.

Tests Summary:

1. FolderTemplate Validation (4 tests)
   - Invalid walk order range (start > end)
   - Invalid folder number (0)
   - Template for non-existent client
   - Empty folder name gets auto-generated

2. FolderTemplate Uniqueness (3 tests)
   - Duplicate folder number for same client (blocked)
   - Overlapping walk order ranges (blocked)
   - Same folder number for different client (allowed)

3. WorkFolder Creation (3 tests)
   - Create folders for period with no templates (blocked)
   - Create folders twice - skips existing
   - Template from wrong client (blocked)

4. WorkFolder Reader Assignment (4 tests)
   - Assign reader updates status to assigned
   - Assign inactive reader (blocked)
   - Assign non-existent reader (blocked)
   - Unassign reader resets status to pending

5. WorkFolder Distribution (3 tests)
   - Distribute with no folders (blocked)
   - Meters without walk_order counted as unmatched
   - Meters outside all ranges counted as unmatched

6. WorkFolder Status (3 tests)
   - Start work on non-assigned folder (blocked)
   - Complete non-in-progress folder (blocked)
   - Valid flow: pending -> assigned -> in_progress -> completed

7. WorkFolder Delete (2 tests)
   - Delete folder with assigned meters (blocked)
   - Delete empty folder (allowed)

8. WorkFolder Release to Reader - mobile app (7 tests)
   - Release a folder: stamped and ready for download
   - Release a folder with no reader (blocked)
   - Download marks the folder, hides it, moves it to in_progress
   - Re-release returns a downloaded folder to the download list
   - Releasing a completed folder returns it to assigned
   - Marking an unreleased folder as downloaded (blocked)
   - Unassigning a reader clears the release

Total: 43 tests
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

client_service = ClientService()
reader_service = ReaderService()
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
    """Create shared test data"""
    global test_client, test_period, test_source_file

    test_client = client_service.create_client("עיריית תיקים בדיקה", "100000030")
    periods = period_service.initialize_periods_for_year(test_client['client_id'], 2026)
    test_period = periods[0]

    test_source_file = source_file_service.upload_period_file(period_id=test_period['period_id'],
        original_filename="test_folders.xlsx",file_type="excel")
    print(f"  Setup: לקוח (ID: {test_client['client_id']}), תקופה 1, קובץ מקור")

def create_test_meters(count=10):
    """Helper: create test meters with walk orders 1100-2000"""
    rows = []
    for i in range(1, count + 1):
        rows.append({ 'row_number': i, 'meter_number': f'MTR-FOLDER-{i:04d}',
            'customer_number': f'CUST-{i:03d}', 'customer_name': f'לקוח תיק {i}',
            'address': f'רחוב תיק {i}', 'walk_order': 1000 + (i * 100),
            'previous_reading': 50.0 * i, 'installation_date': '2020-01-01','raw_data': {'test': i}})
    return rows

def create_meters_with_issues():
    """Helper: create meters - some without walk_order, some outside range"""
    rows = [
        # Normal meters in range 1000-2000
        {'row_number': 1, 'meter_number': 'MTR-OK-001', 'walk_order': 1200, 'previous_reading': 100},
        {'row_number': 2, 'meter_number': 'MTR-OK-002', 'walk_order': 1800, 'previous_reading': 200},
        # Meter without walk_order
        {'row_number': 3, 'meter_number': 'MTR-NO-WO', 'walk_order': None, 'previous_reading': 300},
        # Meter outside all folder ranges
        {'row_number': 4, 'meter_number': 'MTR-OUT-001', 'walk_order': 9999, 'previous_reading': 400},
    ]
    return rows

def create_assigned_folder(corp_number, reader_username):
    """Helper: a fresh client with one folder assigned to a new reader. Returns (folder, reader)."""
    rc = client_service.create_client(f"עיריית שחרור {corp_number}", corp_number)
    rp = period_service.initialize_periods_for_year(rc['client_id'], 2026)[0]
    template_service.create_template(rc['client_id'], 1, "תיק שחרור", 1000, 2000)
    folder_service.create_folders_for_period(rp['period_id'])
    folder = folder_service.get_period_folders(rp['period_id'])[0]

    reader = reader_service.create_reader("קורא שחרור", reader_username, "hash")
    folder_service.assign_reader_to_folder(folder['folder_id'], reader['reader_id'])
    return folder, reader

#  1. FOLDER TEMPLATE VALIDATION

def test_template_invalid_walk_order_range():
    """תבנית עם טווח לא תקין: הפוך, שווה, או שלילי"""
    cases = [
        (2000, 1000, "טווח הפוך"),
        (1500, 1500, "טווח שווה (start==end)"),
        (-100, 200, "start שלילי"),
    ]
    all_ok = True
    for start, end, label in cases:
        try:
            template_service.create_template(test_client['client_id'], 1, f"תיק {label}", start, end)
            report(f"טווח לא תקין: {label}", False, "לא נזרקה שגיאה")
            all_ok = False
        except ValueError:
            report(f"טווח לא תקין: {label}", True)

def test_template_invalid_folder_number():
    """תבנית עם מספר תיק 0"""
    try:
        template_service.create_template(test_client['client_id'], 0, "תיק אפס", 1000, 2000 )
        report("מספר תיק 0", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תיק 0 (חסום)", True)

def test_template_nonexistent_client():
    """תבנית ללקוח שלא קיים"""
    try:
        template_service.create_template(99999, 1, "תיק", 1000, 2000)
        report("תבנית ללקוח לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("תבנית ללקוח לא קיים (חסום)", True)
        except AssertionError as ae:
            report("תבנית ללקוח לא קיים (חסום)", False, str(ae))

def test_template_empty_name_auto_generated():
    """תבנית עם שם ריק - צריך לקבל שם אוטומטי"""
    try:
        template = template_service.create_template(test_client['client_id'], 1, "", 1000, 1500)
        assert template is not None
        assert template['folder_name'] is not None
        assert len(template['folder_name']) > 0
        report("שם ריק - שם אוטומטי", True)
    except AssertionError as e:
        report("שם ריק - שם אוטומטי", False, str(e))


#  2. FOLDER TEMPLATE UNIQUENESS

def test_template_duplicate_folder_number():
    """מספר תיק כפול, ושם תיק כפול, לאותו תאגיד"""
    try:
        template_service.create_template(test_client['client_id'], 1, "תיק כפול", 3000, 4000 )
        report("מספר תיק כפול", False, "לא נזרקה שגיאה")
    except ValueError:
        report("מספר תיק כפול (חסום)", True)

    try:
        template_service.create_template(test_client['client_id'], 95, "תיק 1", 7000, 8000)
        report("שם תיק כפול", False, "לא נזרקה שגיאה")
    except ValueError:
        report("שם תיק כפול (חסום)", True)

def test_template_overlapping_walk_order():
    """טווחי סדר הליכה חופפים"""
    try:
        # Template 1 has range 1000-1500
        template_service.create_template( test_client['client_id'], 2, "תיק חופף", 1200, 1800)
        report("טווח חופף", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "חופף" in str(e)
            report("טווח חופף (חסום)", True)
        except AssertionError as ae:
            report("טווח חופף (חסום)", False, str(ae))

def test_template_same_number_different_client():
    """אותו מספר תיק ללקוח אחר - מותר"""
    other_client = client_service.create_client("עיריית אחרת", "100000031")
    try:
        template = template_service.create_template( other_client['client_id'], 1, "תיק צפון", 1000, 2000 )
        assert template is not None
        report("מספר תיק זהה ללקוח אחר (מותר)", True)
    except AssertionError as e:
        report("מספר תיק זהה ללקוח אחר (מותר)", False, str(e))

#  3. WORK FOLDER CREATION

def test_create_folders_no_templates():
    """יצירת תיקי עבודה לתקופה בלי תבניות"""
    # Create a new client with no templates
    empty_client = client_service.create_client("עיריית ריקה", "100000032")
    empty_periods = period_service.initialize_periods_for_year(empty_client['client_id'], 2026)
    try:
        folder_service.create_folders_for_period(empty_periods[0]['period_id'])
        report("תיקים בלי תבניות", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "אין תבניות" in str(e)
            report("תיקים בלי תבניות (חסום)", True)
        except AssertionError as ae:
            report("תיקים בלי תבניות (חסום)", False, str(ae))

def test_create_folders_twice_skips():
    """יצירת תיקים פעמיים (batch) - מדלג; יצירה בודדת - זורקת שגיאה"""
    try:
        template = template_service.create_template(test_client['client_id'], 2, "תיק דרום", 1501, 2000 )

        folders_first = folder_service.create_folders_for_period(test_period['period_id'])
        assert len(folders_first) == 2

        folders_second = folder_service.create_folders_for_period(test_period['period_id'])
        assert len(folders_second) == 0
        report("יצירה כפולה (batch) מדלגת על קיימים", True)
    except AssertionError as e:
        report("יצירה כפולה (batch) מדלגת על קיימים", False, str(e))

    try:
        folder_service.create_folder_from_template(test_period['period_id'], template['template_id'])
        report("יצירה כפולה (בודד) זורקת שגיאה", False, "לא נזרקה שגיאה")
    except ValueError:
        report("יצירה כפולה (בודד) זורקת שגיאה", True)

def test_create_folder_wrong_client_template():
    """יצירת תיק מתבנית של לקוח אחר"""
    other_client = client_service.create_client("עיריית זרה", "100000033")
    other_template = template_service.create_template(other_client['client_id'], 1, "תיק זר", 5000, 6000 )
    try:
        folder_service.create_folder_from_template( test_period['period_id'], other_template['template_id'] )
        report("תבנית מלקוח אחר", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא שייכת" in str(e)
            report("תבנית מלקוח אחר (חסום)", True)
        except AssertionError as ae:
            report("תבנית מלקוח אחר (חסום)", False, str(ae))

def test_update_template_partial_range():
    """עדכון טווח חלקי (רק start) - end נלקח מהערך הקיים, ולידציה רצה מחדש"""
    try:
        rc = client_service.create_client("עיריית עדכון תבנית", "100000037")
        template = template_service.create_template(rc['client_id'], 1, "תיק לעדכון", 1000, 2000)

        # עדכון רק start - end נשאר 2000
        updated = template_service.update_template(template['template_id'], walk_order_start=1500)
        assert updated is True
        fetched = template_service.get_template(template['template_id'])
        assert fetched['walk_order_start'] == 1500
        assert fetched['walk_order_end'] == 2000

        # עדכון שיוצר טווח לא תקין (start > end הקיים) - צריך להיכשל
        try:
            template_service.update_template(template['template_id'], walk_order_start=2500)
            report("עדכון start בלבד (מותר) + ולידציה על טווח לא תקין", False, "לא נזרקה שגיאה על טווח הפוך")
        except ValueError:
            report("עדכון start בלבד (מותר) + ולידציה על טווח לא תקין", True)
    except AssertionError as e:
        report("עדכון start בלבד (מותר) + ולידציה על טווח לא תקין", False, str(e))

#  4. WORK FOLDER READER ASSIGNMENT

def test_assign_reader_updates_status():
    """שיוך קורא מעדכן סטטוס ל-assigned"""
    try:
        folders = folder_service.get_period_folders(test_period['period_id'])

        # Create a test reader for this test
        test_reader = reader_service.create_reader( name="קורא לשיוך", username="assign_test", password_hash="hash123")

        folder_service.assign_reader_to_folder(folders[0]['folder_id'], test_reader['reader_id'])
        updated = folder_service.get_folder(folders[0]['folder_id'])
        assert updated['status'] == 'assigned'
        assert updated['assigned_to'] == test_reader['reader_id']
        report("שיוך קורא - סטטוס assigned", True)
    except AssertionError as e:
        report("שיוך קורא - סטטוס assigned", False, str(e))

def test_assign_inactive_reader():
    """שיוך קורא לא פעיל"""
    # Create and deactivate a reader
    inactive = reader_service.create_reader("קורא מושבת", "inactive_test", "hash123")
    reader_service.deactivate_reader(inactive['reader_id'])

    folders = folder_service.get_period_folders(test_period['period_id'])
    try:
        folder_service.assign_reader_to_folder(folders[1]['folder_id'], inactive['reader_id'])
        report("שיוך קורא לא פעיל", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא פעיל" in str(e)
            report("שיוך קורא לא פעיל (חסום)", True)
        except AssertionError as ae:
            report("שיוך קורא לא פעיל (חסום)", False, str(ae))

def test_assign_nonexistent_reader():
    """שיוך קורא שלא קיים"""
    folders = folder_service.get_period_folders(test_period['period_id'])
    try:
        folder_service.assign_reader_to_folder(folders[1]['folder_id'], 99999)
        report("שיוך קורא לא קיים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא נמצא" in str(e)
            report("שיוך קורא לא קיים (חסום)", True)
        except AssertionError as ae:
            report("שיוך קורא לא קיים (חסום)", False, str(ae))

def test_unassign_reader_resets_status():
    """הסרת שיוך קורא מחזירה סטטוס ל-pending"""
    try:
        folders = folder_service.get_period_folders(test_period['period_id'])
        # Folder 0 is assigned from earlier test
        folder_service.unassign_reader_from_folder(folders[0]['folder_id'])
        updated = folder_service.get_folder(folders[0]['folder_id'])
        assert updated['status'] == 'pending'
        assert updated['assigned_to'] is None
        report("הסרת שיוך - חזרה ל-pending", True)
    except AssertionError as e:
        report("הסרת שיוך - חזרה ל-pending", False, str(e))

def test_assign_meter_to_folder_without_reader_is_assigned_to_folder():
    """מונה שמשויך לתיק ללא קורא - סטטוס צריך להיות assigned_to_folder"""
    try:
        # Create fresh folder without reader
        period_5 = period_service.get_period_by_identity(test_client['client_id'], 2026, 5)
        folder_service.create_folders_for_period(period_5['period_id'])
        folders = folder_service.get_period_folders(period_5['period_id'])
        test_folder = folders[0]

        # Create a meter and assign to folder
        sf = source_file_service.upload_period_file(
            period_id=period_5['period_id'], original_filename="test5.xlsx", file_type="excel")
        meter_service.create_meters_from_parsed_rows(
            period_5['period_id'], sf['source_file_id'],
            [{'row_number': 1, 'meter_number': 'MTR-STATUS-001', 'walk_order': 1200}])

        meters = meter_service.get_period_meters(period_5['period_id'])
        meter_service.assign_meter_to_folder(meters[0]['period_meter_id'], test_folder['folder_id'])

        updated = meter_service.get_meter(meters[0]['period_meter_id'])
        assert updated['work_status'] == 'assigned_to_folder'
        report("מונה בתיק ללא קורא → assigned_to_folder", True)
    except AssertionError as e:
        report("מונה בתיק ללא קורא → assigned_to_folder", False, str(e))

def test_assign_reader_promotes_meters_to_assigned_to_reader():
    """שיוך קורא לתיק - כל המונים עוברים מ-assigned_to_folder ל-assigned_to_reader"""
    try:
        period_5 = period_service.get_period_by_identity(test_client['client_id'], 2026, 5)
        folders = folder_service.get_period_folders(period_5['period_id'])
        test_folder = folders[0]

        # Assign reader
        new_reader = reader_service.create_reader(
            name="קורא סטטוס", username="status_reader_1", password_hash="hash")
        folder_service.assign_reader_to_folder(test_folder['folder_id'], new_reader['reader_id'])

        # Check all meters promoted
        meters = meter_service.get_folder_meters(test_folder['folder_id'])
        all_promoted = all(m['work_status'] == 'assigned_to_reader' for m in meters)
        assert all_promoted
        report("שיוך קורא לתיק → כל המונים assigned_to_reader", True)
    except AssertionError as e:
        report("שיוך קורא לתיק → כל המונים assigned_to_reader", False, str(e))

def test_assign_reader_to_already_assigned_folder_blocked():
    """שיוך קורא לתיק שכבר משויך לקורא אחר - חסום ברמת השירות"""
    try:
        rc = client_service.create_client("עיריית קונפליקט קורא", "100000036")
        rp = period_service.initialize_periods_for_year(rc['client_id'], 2026)[0]
        template_service.create_template(rc['client_id'], 1, "תיק קונפליקט", 1000, 2000)
        folder_service.create_folders_for_period(rp['period_id'])
        folders = folder_service.get_period_folders(rp['period_id'])
        test_folder = folders[0]

        reader_a = reader_service.create_reader("קורא א קונפליקט", "conflict_reader_a", "hash")
        reader_b = reader_service.create_reader("קורא ב קונפליקט", "conflict_reader_b", "hash")

        folder_service.assign_reader_to_folder(test_folder['folder_id'], reader_a['reader_id'])

        # קורא אחר → חסום
        try:
            folder_service.assign_reader_to_folder(test_folder['folder_id'], reader_b['reader_id'])
            report("שיוך לתיק תפוס (חסום)", False, "לא נזרקה שגיאה")
        except ValueError as e:
            assert "כבר משויך" in str(e)
            report("שיוך לתיק תפוס (חסום)", True)

        # אותו קורא שוב → מותר, לא אמור לזרוק
        result = folder_service.assign_reader_to_folder(test_folder['folder_id'], reader_a['reader_id'])
        assert result is True
        report("שיוך חוזר לאותו קורא (מותר)", True)
    except AssertionError as e:
        report("קונפליקט/חזרה על שיוך קורא", False, str(e))

def test_unassign_reader_demotes_meters_to_assigned_to_folder():
    """הסרת קורא מתיק - כל המונים חוזרים מ-assigned_to_reader ל-assigned_to_folder"""
    try:
        period_5 = period_service.get_period_by_identity(test_client['client_id'], 2026, 5)
        folders = folder_service.get_period_folders(period_5['period_id'])
        test_folder = folders[0]

        # Unassign reader
        folder_service.unassign_reader_from_folder(test_folder['folder_id'])

        # Check all meters demoted
        meters = meter_service.get_folder_meters(test_folder['folder_id'])
        all_demoted = all(m['work_status'] == 'assigned_to_folder' for m in meters)
        assert all_demoted
        report("הסרת קורא מתיק → כל המונים assigned_to_folder", True)
    except AssertionError as e:
        report("הסרת קורא מתיק → כל המונים assigned_to_folder", False, str(e))


#  5. WORK FOLDER DISTRIBUTION

def test_distribute_no_folders():
    """חלוקת מונים כשאין תיקי עבודה"""
    # Create period without folders
    period_3 = period_service.get_period_by_identity(test_client['client_id'], 2026, 3)
    try:
        folder_service.distribute_meters_into_folders(period_3['period_id'])
        report("חלוקה בלי תיקים", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "אין תיקי" in str(e)
            report("חלוקה בלי תיקים (חסום)", True)
        except AssertionError as ae:
            report("חלוקה בלי תיקים (חסום)", False, str(ae))

def test_distribute_meters_without_walk_order():
    """מונים בלי walk_order נספרים כ-unmatched"""
    try:
        # Create meters with issues in period 2
        period_2 = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)
        sf_2 = source_file_service.upload_period_file( period_id=period_2['period_id'],
            original_filename="issues.xlsx",file_type="excel" )
        meter_service.create_meters_from_parsed_rows( period_2['period_id'], sf_2['source_file_id'], create_meters_with_issues())

        # Create folders for period 2
        folder_service.create_folders_for_period(period_2['period_id'])

        # Distribute
        result = folder_service.distribute_meters_into_folders(period_2['period_id'])

        # MTR-NO-WO has no walk_order, MTR-OUT-001 is outside range
        assert result['unmatched'] >= 1  # At least the None walk_order
        report("מונים בלי walk_order = unmatched", True)
    except AssertionError as e:
        report("מונים בלי walk_order = unmatched", False, str(e))

def test_distribute_meters_outside_range():
    """מונים מחוץ לטווח כל התיקים נספרים כ-unmatched"""
    try:
        period_2 = period_service.get_period_by_identity(test_client['client_id'], 2026, 2)

        # Run distribute again - unmatched meters are still there
        result = folder_service.distribute_meters_into_folders(period_2['period_id'])

        # MTR-OUT-001 (walk_order=9999) and MTR-NO-WO (no walk_order) are still unmatched
        assert result['unmatched'] == 2
        assert result['assigned'] == 0  # The 2 good ones were already assigned
        report("מונים מחוץ לטווח = unmatched", True)
    except AssertionError as e:
        report("מונים מחוץ לטווח = unmatched", False, str(e))

def test_distribute_meters_to_folder_with_reader_is_assigned_to_reader():
    """חלוקת מונים לתיק שכבר יש לו קורא - סטטוס צריך להיות assigned_to_reader"""
    try:
        period_6 = period_service.get_period_by_identity(test_client['client_id'], 2026, 6)
        folder_service.create_folders_for_period(period_6['period_id'])
        folders = folder_service.get_period_folders(period_6['period_id'])
        test_folder = folders[0]

        # Assign reader BEFORE distributing meters
        new_reader = reader_service.create_reader(
            name="קורא סטטוס 2", username="status_reader_2", password_hash="hash")
        folder_service.assign_reader_to_folder(test_folder['folder_id'], new_reader['reader_id'])

        # Now create and distribute meters
        sf = source_file_service.upload_period_file(
            period_id=period_6['period_id'], original_filename="test6.xlsx", file_type="excel")
        meter_service.create_meters_from_parsed_rows(
            period_6['period_id'], sf['source_file_id'],
            [{'row_number': 1, 'meter_number': 'MTR-STATUS-002', 'walk_order': 1200}])

        folder_service.distribute_meters_into_folders(period_6['period_id'])

        meters = meter_service.get_folder_meters(test_folder['folder_id'])
        assert all(m['work_status'] == 'assigned_to_reader' for m in meters)
        report("חלוקה לתיק עם קורא → assigned_to_reader", True)
    except AssertionError as e:
        report("חלוקה לתיק עם קורא → assigned_to_reader", False, str(e))

#  6. WORK FOLDER STATUS

def test_start_work_on_pending_folder():
    """התחלת עבודה על תיק ב-pending (צריך assigned קודם)"""
    folders = folder_service.get_period_folders(test_period['period_id'])
    # Folder 0 is pending (we unassigned earlier)
    try:
        folder_service.start_folder_work(folders[0]['folder_id'])
        report("start_work על pending", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "assigned" in str(e)
            report("start_work על pending (חסום)", True)
        except AssertionError as ae:
            report("start_work על pending (חסום)", False, str(ae))

def test_complete_non_in_progress_folder():
    """השלמת תיק שלא ב-in_progress"""
    folders = folder_service.get_period_folders(test_period['period_id'])
    try:
        folder_service.complete_folder(folders[0]['folder_id'])
        report("complete על pending", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "in_progress" in str(e)
            report("complete על pending (חסום)", True)
        except AssertionError as ae:
            report("complete על pending (חסום)", False, str(ae))

def test_valid_folder_status_flow():
    """מעבר סטטוסים תקין: pending -> assigned -> in_progress -> completed"""
    try:
        folders = folder_service.get_period_folders(test_period['period_id'])
        test_folder = folders[0]

        # Create a test reader for this test
        status_reader = reader_service.create_reader(name="קורא לסטטוס", username="status_flow_test", password_hash="hash123")

        # pending -> assigned
        folder_service.assign_reader_to_folder(test_folder['folder_id'], status_reader['reader_id'])
        updated = folder_service.get_folder(test_folder['folder_id'])
        assert updated['status'] == 'assigned'

        # assigned -> in_progress
        folder_service.start_folder_work(test_folder['folder_id'])
        updated = folder_service.get_folder(test_folder['folder_id'])
        assert updated['status'] == 'in_progress'

        # in_progress -> completed
        folder_service.complete_folder(test_folder['folder_id'])
        updated = folder_service.get_folder(test_folder['folder_id'])
        assert updated['status'] == 'completed'
        assert updated['completed_at'] is not None

        report("מעבר סטטוסים תקין (pending->assigned->in_progress->completed)", True)
    except AssertionError as e:
        report("מעבר סטטוסים תקין (pending->assigned->in_progress->completed)", False, str(e))

#  7. WORK FOLDER DELETE

def test_delete_folder_with_meters():
    """מחיקת תיק שיש בו מונים - משחרר מונים ומוחק"""
    try:
        # Create meters and assign to folder
        rows = create_test_meters(3)
        meter_service.create_meters_from_parsed_rows( test_period['period_id'], test_source_file['source_file_id'], rows)

        folders = folder_service.get_period_folders(test_period['period_id'])
        meters = meter_service.get_period_meters(test_period['period_id'])  # Assign meters to folder 1 (the non-completed one)

        assigned_meter_id = None
        for m in meters:
            if m['folder_id'] is None:
                meter_service.assign_meter_to_folder(m['period_meter_id'], folders[1]['folder_id'])
                assigned_meter_id = m['period_meter_id']
                break

        folder_service.delete_folder(folders[1]['folder_id'])

        # וודא שהתיק נמחק
        deleted = folder_service.get_folder(folders[1]['folder_id'])
        assert deleted is None

        # וודא שהמונה שוחרר
        released = meter_service.get_meter(assigned_meter_id)
        assert released['folder_id'] is None
        assert released['work_status'] == 'new'

        report("מחיקת תיק עם מונים - שחרור מונים", True)
    except AssertionError as e:
        report("מחיקת תיק עם מונים - שחרור מונים", False, str(e))

def test_delete_period_folders_releases_meters():
    """מחיקת כל תיקי התקופה - משחררת את כל המונים ומוחקת את כל התיקים"""
    try:
        # תקופה 4 כבר יש לה תיק ריק אחד ממחיקה קודמת - ניצור תקופה נקייה
        period_7 = period_service.get_period_by_identity(test_client['client_id'], 2026, 4)
        # ליצור עוד תבנית/תיק ולוודא שיש לפחות תיק אחד עם מונה משויך
        sf_7 = source_file_service.upload_period_file(
            period_id=period_7['period_id'], original_filename="test7.xlsx", file_type="excel")
        meter_service.create_meters_from_parsed_rows(
            period_7['period_id'], sf_7['source_file_id'],
            [{'row_number': 1, 'meter_number': 'MTR-BULK-DEL-001', 'walk_order': 1200}])

        folder_service.create_folders_for_period(period_7['period_id'])
        folder_service.distribute_meters_into_folders(period_7['period_id'])

        folders_before = folder_service.get_period_folders(period_7['period_id'])
        assert len(folders_before) > 0

        deleted_count = folder_service.delete_period_folders(period_7['period_id'])
        assert deleted_count == len(folders_before)

        # כל התיקים נמחקו
        folders_after = folder_service.get_period_folders(period_7['period_id'])
        assert len(folders_after) == 0

        # המונה שוחרר, לא נמחק
        meter = meter_service.get_meter_by_number(period_7['period_id'], 'MTR-BULK-DEL-001')
        assert meter is not None
        assert meter['folder_id'] is None
        assert meter['work_status'] == 'new'

        report("delete_period_folders משחררת מונים ומוחקת הכל", True)
    except AssertionError as e:
        report("delete_period_folders משחררת מונים ומוחקת הכל", False, str(e))

def test_delete_empty_folder():
    """מחיקת תיק ריק - מותר"""
    try:
        # Create a new period with empty folders
        period_4 = period_service.get_period_by_identity(test_client['client_id'], 2026, 4)
        folder_service.create_folders_for_period(period_4['period_id'])
        folders = folder_service.get_period_folders(period_4['period_id'])

        result = folder_service.delete_folder(folders[0]['folder_id'])
        assert result is True
        report("מחיקת תיק ריק (מותר)", True)
    except AssertionError as e:
        report("מחיקת תיק ריק (מותר)", False, str(e))

def test_delete_template_without_folders_succeeds():
    """מחיקת תבנית שאין לה תיקי עבודה - מותר"""
    try:
        clean_client = client_service.create_client("עיריית תבנית נקייה", "100000034")
        template = template_service.create_template(clean_client['client_id'], 1, "תיק למחיקה", 1000, 2000)

        result = template_service.delete_template(template['template_id'])
        assert result is True

        fetched = template_service.get_template(template['template_id'])
        assert fetched is None
        report("מחיקת תבנית בלי תיקים (מותר)", True)
    except AssertionError as e:
        report("מחיקת תבנית בלי תיקים (מותר)", False, str(e))

def test_delete_template_with_folders_raises_db_error():
    """מחיקת תבנית שיש לה תיקי עבודה - נכשלת (RESTRICT), לא נמחק כלום"""
    try:
        rc = client_service.create_client("עיריית תבנית תפוסה", "100000035")
        rp = period_service.initialize_periods_for_year(rc['client_id'], 2026)[0]
        template = template_service.create_template(rc['client_id'], 1, "תיק תפוס", 1000, 2000)
        folder_service.create_folders_for_period(rp['period_id'])

        try:
            template_service.delete_template(template['template_id'])
            report("מחיקת תבנית עם תיקים (RESTRICT)", False, "לא נזרקה שגיאה כלשהי")
        except Exception:
            # לא בהכרח ValueError - כרגע זו שגיאת DB גולמית, לפי ההחלטה שקיבלנו
            still_exists = template_service.get_template(template['template_id'])
            assert still_exists is not None
            report("מחיקת תבנית עם תיקים (RESTRICT, לא נמחק)", True)
    except AssertionError as e:
        report("מחיקת תבנית עם תיקים (RESTRICT, לא נמחק)", False, str(e))

#  8. WORK FOLDER RELEASE TO READER (mobile app)

def test_release_folder_ready_for_download():
    """שחרור תיק לקורא - מקבל חותמת זמן ומופיע ברשימת ההורדה"""
    try:
        folder, reader = create_assigned_folder("100000040", "release_reader_1")

        folder_service.release_folder(folder['folder_id'], include_previous_readings=False)

        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['released_at'] is not None
        assert updated['include_previous_readings'] is False
        assert updated['downloaded_at'] is None
        assert updated['status'] == 'assigned'

        ready = folder_service.get_folders_ready_for_download(reader['reader_id'])
        assert [f['folder_id'] for f in ready] == [folder['folder_id']]
        report("שחרור תיק - מוכן להורדה", True)
    except AssertionError as e:
        report("שחרור תיק - מוכן להורדה", False, str(e))

def test_release_folder_without_reader_blocked():
    """שחרור תיק שלא משויך לקורא - חסום"""
    folder, _ = create_assigned_folder("100000041", "release_reader_2")
    folder_service.unassign_reader_from_folder(folder['folder_id'])
    try:
        folder_service.release_folder(folder['folder_id'], include_previous_readings=True)
        report("שחרור תיק בלי קורא", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא משויך" in str(e)
            report("שחרור תיק בלי קורא (חסום)", True)
        except AssertionError as ae:
            report("שחרור תיק בלי קורא (חסום)", False, str(ae))

def test_download_marks_hides_and_starts_work():
    """הורדה מסמנת את התיק, מעלימה אותו מהרשימה, ומעבירה ל-in_progress"""
    try:
        folder, reader = create_assigned_folder("100000042", "release_reader_3")
        folder_service.release_folder(folder['folder_id'], include_previous_readings=True)

        folder_service.mark_folder_downloaded(folder['folder_id'])

        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['downloaded_at'] is not None
        assert updated['status'] == 'in_progress'

        ready = folder_service.get_folders_ready_for_download(reader['reader_id'])
        assert ready == []
        report("הורדה - מסומן, נעלם מהרשימה, in_progress", True)
    except AssertionError as e:
        report("הורדה - מסומן, נעלם מהרשימה, in_progress", False, str(e))

def test_re_release_returns_folder_to_download():
    """שחרור חוזר של תיק שהורד - חוזר לרשימת ההורדה, נשאר in_progress"""
    try:
        folder, reader = create_assigned_folder("100000043", "release_reader_4")
        folder_service.release_folder(folder['folder_id'], include_previous_readings=True)
        folder_service.mark_folder_downloaded(folder['folder_id'])

        # Re-release after a problem in the readings
        folder_service.release_folder(folder['folder_id'], include_previous_readings=True)

        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['downloaded_at'] is None
        assert updated['status'] == 'in_progress'

        ready = folder_service.get_folders_ready_for_download(reader['reader_id'])
        assert [f['folder_id'] for f in ready] == [folder['folder_id']]

        # Downloading again keeps in_progress, without an error
        folder_service.mark_folder_downloaded(folder['folder_id'])
        assert folder_service.get_folder(folder['folder_id'])['status'] == 'in_progress'
        report("שחרור חוזר - חוזר לרשימה, נשאר in_progress", True)
    except AssertionError as e:
        report("שחרור חוזר - חוזר לרשימה, נשאר in_progress", False, str(e))

def test_release_completed_folder_returns_to_assigned():
    """שחרור תיק שהושלם - חוזר ל-assigned, וההורדה מעבירה ל-in_progress"""
    try:
        folder, _ = create_assigned_folder("100000044", "release_reader_5")
        folder_service.start_folder_work(folder['folder_id'])
        folder_service.complete_folder(folder['folder_id'])

        folder_service.release_folder(folder['folder_id'], include_previous_readings=True)

        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['status'] == 'assigned'
        assert updated['completed_at'] is None

        folder_service.mark_folder_downloaded(folder['folder_id'])
        assert folder_service.get_folder(folder['folder_id'])['status'] == 'in_progress'
        report("שחרור תיק שהושלם - assigned, ואז in_progress", True)
    except AssertionError as e:
        report("שחרור תיק שהושלם - assigned, ואז in_progress", False, str(e))

def test_mark_unreleased_folder_downloaded_blocked():
    """סימון הורדה לתיק שלא שוחרר - חסום"""
    folder, _ = create_assigned_folder("100000045", "release_reader_6")
    try:
        folder_service.mark_folder_downloaded(folder['folder_id'])
        report("סימון הורדה לתיק לא משוחרר", False, "לא נזרקה שגיאה")
    except ValueError as e:
        try:
            assert "לא שוחרר" in str(e)
            report("סימון הורדה לתיק לא משוחרר (חסום)", True)
        except AssertionError as ae:
            report("סימון הורדה לתיק לא משוחרר (חסום)", False, str(ae))

def test_unassign_reader_clears_release():
    """הסרת קורא מתיק משוחרר - השחרור מתאפס והתיק לא מוכן להורדה"""
    try:
        folder, reader = create_assigned_folder("100000046", "release_reader_7")
        folder_service.release_folder(folder['folder_id'], include_previous_readings=False)

        folder_service.unassign_reader_from_folder(folder['folder_id'])

        updated = folder_service.get_folder(folder['folder_id'])
        assert updated['released_at'] is None
        assert updated['downloaded_at'] is None
        assert updated['include_previous_readings'] is True  # Back to default

        ready = folder_service.get_folders_ready_for_download(reader['reader_id'])
        assert ready == []
        report("הסרת קורא - השחרור מתאפס", True)
    except AssertionError as e:
        report("הסרת קורא - השחרור מתאפס", False, str(e))

#  RUN ALL TESTS

def main():
    reset_counters()

    print("=" * 50)
    print("  Monim tests: Folder Error Tests")
    print("=" * 50)

    try: 
        # Setup
        print("\n=== הכנה ===")
        setup()

        # 1. Template validation
        print("\n=== בדיקות תבנית : ולידציה ===")
        test_template_invalid_walk_order_range()
        test_template_invalid_folder_number()
        test_template_nonexistent_client()
        test_template_empty_name_auto_generated()

        # 2. Template uniqueness
        print("\n=== בדיקות תבנית : ייחודיות ===")
        test_template_duplicate_folder_number()
        test_template_overlapping_walk_order()
        test_template_same_number_different_client()

        # 3. WorkFolder creation
        print("\n=== בדיקות יצירת תיקי עבודה ===")
        test_create_folders_no_templates()
        test_create_folders_twice_skips()
        test_create_folder_wrong_client_template()
        test_update_template_partial_range()

        # 4. Reader assignment
        print("\n=== בדיקות שיוך קורא ===")
        test_assign_reader_updates_status()
        test_assign_inactive_reader()
        test_assign_nonexistent_reader()
        test_unassign_reader_resets_status()
        test_assign_meter_to_folder_without_reader_is_assigned_to_folder()
        test_assign_reader_promotes_meters_to_assigned_to_reader()
        test_assign_reader_to_already_assigned_folder_blocked()
        test_unassign_reader_demotes_meters_to_assigned_to_folder()
        
        # 5. Distribution
        print("\n=== בדיקות חלוקת מונים ===")
        test_distribute_no_folders()
        test_distribute_meters_without_walk_order()
        test_distribute_meters_outside_range()
        test_distribute_meters_to_folder_with_reader_is_assigned_to_reader()
        
        # 6. Status
        print("\n=== בדיקות סטטוס תיק ===")
        test_start_work_on_pending_folder()
        test_complete_non_in_progress_folder()
        test_valid_folder_status_flow()

        # 7. Delete
        print("\n=== בדיקות מחיקה ===")
        test_delete_folder_with_meters()
        test_delete_period_folders_releases_meters()
        test_delete_empty_folder()
        test_delete_template_without_folders_succeeds()
        test_delete_template_with_folders_raises_db_error()

        # 8. Release to reader (mobile app)
        print("\n=== בדיקות שחרור לקורא (אפליקציה) ===")
        test_release_folder_ready_for_download()
        test_release_folder_without_reader_blocked()
        test_download_marks_hides_and_starts_work()
        test_re_release_returns_folder_to_download()
        test_release_completed_folder_returns_to_assigned()
        test_mark_unreleased_folder_downloaded_blocked()
        test_unassign_reader_clears_release()

        # Summary
        print("\n" + "=" * 50)
        print_summary()
        print("=" * 50)

    finally:
        # Cleanup
        cleanup()


if __name__ == "__main__":
    main()