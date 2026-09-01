"""
Monim - Happy Path Flow Test
Full end-to-end business flow test using a real source file and the real parsing pipeline (no hand-built rows, no bypassed steps).
Proves the architecture works from client creation to reading approval - including realistic, imperfect data.

Tests Summary:

1. Create Client
   - Create new client and verify it's saved

2. Create Reading Periods
   - Initialize 6 periods for the year
   - Verify previous period lookup

3. Upload Source File
   - Upload real netanya_sample.xlsx (shared with parsing_tests) for period 1
   - Verify period status updates to file_received

4. Process Uploaded File (real parser)
   - Run process_uploaded_file end-to-end: parsing, row classification, meter creation.
   - Verify period status advances to active
   - Verify status summary: 10 meters total, 9 'new', 1 'missing_info (one row in the sample file has no walk_order)

5. Create Work Folders
   - Create folder templates with walk order ranges matching the real data 
   (not round numbers - the source file's walk_order values are large and unevenly distributed)
   - Create work folders from templates
   - Distribute meters into folders by walk order
   - Verify uneven split (3 + 6 = 9 assigned); the 1 meter missing walk_order is correctly left unmatched, 
    not silently dropped or force-assigned

6. Assign Reader to Folder
   - Assign reader to folder
   - Verify status updates to assigned

7. Create and Approve Reading
   - Create reading with consumption calculation
   - Verify meter and folder state updates
   - Approve reading and verify completion

Total: 7 steps with multiple assertions each.

Error handling: each step runs through run_step(), which reports AssertionErrors via report() and re-raises to stop the run immediately,
since later steps depend on earlier state. Other exceptions (bugs, DB errors) propagate with a full traceback rather than being swallowed.
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
from src.services.reader_service import ReaderService
from src.services.reading_service import ReadingService

client_service = ClientService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
reader_service = ReaderService()
reading_service = ReadingService()

# Shared state between steps
test_data = {}

# Points to the real fixture used by the parser tests, so this flow
# exercises the actual parsing + meter-creation pipeline instead of bypassing it with hand-built rows.
NETANYA_SAMPLE_PATH = os.path.join(os.path.dirname(__file__), '..', 'parsing_tests', 'test_data', 'netanya_sample.xlsx')

# helper
def run_step(step_func, step_name):
    """מריץ שלב יחיד; בכישלון מדווח יפה ועוצר את הריצה (השלבים תלויים זה בזה)"""
    try:
        step_func()
    except AssertionError as e:
        report(step_name, False, str(e))
        raise

#  STEP 1: Create Client

def test_step1_create_client():
    """יצירת לקוח חדש ואימות"""
    client = client_service.create_client("עיריית בדיקה", "123456789")
    assert client is not None
    assert client['client_id'] is not None
    assert client['name'] == "עיריית בדיקה"
    assert client['corporation_number'] == "123456789"

    # Verify fetch
    fetched = client_service.get_client(client['client_id'])
    assert fetched is not None
    assert fetched['client_id'] == client['client_id']
    assert fetched['name'] == client['name']

    test_data['client'] = client
    report("יצירת לקוח + שליפה חזרה", True)

#  STEP 2: Create Reading Periods

def test_step2_create_periods():
    """יצירת 6 תקופות קריאה ובדיקת תקופה קודמת"""
    client = test_data['client']

    periods = period_service.initialize_periods_for_year(client['client_id'], 2026)
    assert len(periods) == 6

    # Verify each period
    for i, p in enumerate(periods):
        assert p['period_number'] == i + 1
        assert p['status'] == 'pending'
        assert p['year'] == 2026

    # Test previous period lookup
    period_3 = period_service.get_period_by_identity(client['client_id'], 2026, 3)
    previous = period_service.get_previous_period(period_3['period_id'])
    assert previous is not None
    assert previous['period_number'] == 2

    test_data['periods'] = periods
    test_data['test_period'] = periods[0]

    report("יצירת 6 תקופות + תקופה קודמת", True)
    #print(f"    תקופות: {', '.join([f'{p['period_number']}({p['start_date']}-{p['end_date']})' for p in periods])}")
    period_list = ", ".join([f"{p['period_number']}({p['start_date']}-{p['end_date']})" for p in periods])
    print(f"    תקופות: {period_list}")
    
#  STEP 3: Upload Source File

def test_step3_upload_source_file():
    """העלאת קובץ מקור אמיתי (Excel) ואימות עדכון סטטוס תקופה"""
    test_period = test_data['test_period']

    source_file = source_file_service.upload_period_file(
        period_id=test_period['period_id'], original_filename="netanya_sample.xlsx", file_type="netanya_format",
        uploaded_by="מנהל בדיקה", stored_filename="netanya_sample_stored.xlsx", file_path=NETANYA_SAMPLE_PATH)

    assert source_file is not None
    assert source_file['processing_status'] == 'pending'
    assert source_file['original_filename'] == "netanya_sample.xlsx"

    # Verify period status updated
    updated_period = period_service.get_period(test_period['period_id'])
    assert updated_period['status'] == 'file_received'

    test_data['source_file'] = source_file

    report("העלאת קובץ + סטטוס תקופה file_received", True)

#  STEP 4: Process Uploaded File (real parser)

def test_step4_process_file():
    """עיבוד הקובץ בפועל (פרסור אמיתי) - יצירת מונים ועדכון סטטוס תקופה ל-active"""
    source_file = test_data['source_file']
    test_period = test_data['test_period']

    result = source_file_service.process_uploaded_file(source_file['source_file_id'])
    assert result is not None
    # netanya_sample.xlsx: 10 rows, all have meter_number -> 0% skipped -> 'success'.
    # 1 row is missing walk_order -> becomes missing_info, but that's NOT a "skip".
    assert result['processing_status'] == 'success'

    # Verify period status advanced to active after processing
    updated_period = period_service.get_period(test_period['period_id'])
    assert updated_period['status'] == 'active'

    # Verify meters were actually created by the real parser
    all_meters = meter_service.get_period_meters(test_period['period_id'])
    assert len(all_meters) == 10

    # Verify status summary reflects the real data quirk (1 row missing walk_order)
    summary = meter_service.get_period_status_summary(test_period['period_id'])
    assert summary['total'] == 10
    assert summary['unassigned'] == 10
    assert summary['new'] == 9
    assert summary['missing_info'] == 1

    test_data['meters'] = all_meters

    report("עיבוד קובץ אמיתי (פרסור) + 10 מונים + 1 עם missing_info", True)
    print(f"    סיכום: {summary}")

#  STEP 5: Create folder-tempalets + foldres

def test_step5_create_folders():
    """יצירת תבניות, תיקי עבודה, וחלוקת מונים לפי walk_order אמיתי"""
    client = test_data['client']
    test_period = test_data['test_period']

    # Ranges reflect the real walk_order values in netanya_sample.xlsx:
    # rows 1-3 fall in the lower range, rows 4,6-10 cluster in the upper one.
    template1 = template_service.create_template(client_id=client['client_id'],
        folder_number=1, folder_name="תיק צפון", walk_order_start=1, walk_order_end=1_010_002_000)
    assert template1 is not None

    template2 = template_service.create_template(client_id=client['client_id'],
        folder_number=2, folder_name="תיק דרום", walk_order_start=1_010_002_001, walk_order_end=1_010_500_000)
    assert template2 is not None

    # Create work folders
    folders = folder_service.create_folders_for_period(test_period['period_id'])
    assert len(folders) == 2

    # Distribute meters
    distribution = folder_service.distribute_meters_into_folders(test_period['period_id'])
    # The 1 meter missing walk_order can't match any template range
    assert distribution['assigned'] == 9
    assert distribution['unmatched'] == 1
    assert distribution['total_unassigned'] == 10

    # Verify folder contents
    period_folders = folder_service.get_period_folders(test_period['period_id'])
    folder1_meters = meter_service.get_folder_meters(period_folders[0]['folder_id'])
    folder2_meters = meter_service.get_folder_meters(period_folders[1]['folder_id'])
    assert len(folder1_meters) == 3
    assert len(folder2_meters) == 6

    test_data['folders'] = period_folders

    report("תבניות + תיקים + חלוקת 9 מונים (3+6), 1 ללא שיבוץ (walk_order חסר)", True)

#  STEP 6: Assign Reader to Folder

def test_step6_assign_reader():
    """שיוך קורא לתיק ואימות סטטוס"""
    folders = test_data['folders']
    
    # Create a test reader for this flow
    test_reader = reader_service.create_reader(name="קורא בדיקה", username="test_reader", password_hash="test_hash", phone="0501234567")
    test_folder = folders[0]

    folder_service.assign_reader_to_folder(test_folder['folder_id'], test_reader['reader_id'])

    # Verify
    updated_folder = folder_service.get_folder(test_folder['folder_id'])
    assert updated_folder['status'] == 'assigned'
    assert updated_folder['assigned_to'] == test_reader['reader_id']

    # Verify reader's folders
    reader_folders = folder_service.get_reader_folders(test_reader['reader_id'])
    assert len(reader_folders) >= 1

    # Verify meter-level status cascaded from folder assignment
    folder_meters = meter_service.get_folder_meters(test_folder['folder_id'])
    assert len(folder_meters) > 0
    for m in folder_meters:
        assert m['work_status'] == 'assigned_to_reader'

    test_data['test_reader'] = test_reader
    test_data['test_folder'] = test_folder

    report(f"שיוך קורא {test_reader['name']} לתיק + סטטוס assigned", True)

#  STEP 7: Create and Approve Reading

def test_step7_create_reading():
    """יצירת קריאה, אימות חישובים ועדכוני מצב, ואישור"""
    test_folder = test_data['test_folder']
    test_reader = test_data['test_reader']

    # Get a meter
    folder_meters = meter_service.get_folder_meters(test_folder['folder_id'])
    test_meter = folder_meters[0]

    # Create reading
    reading = reading_service.create_reading(period_meter_id=test_meter['period_meter_id'],
        reader_id=test_reader['reader_id'], current_reading=250.5, notes="קריאת בדיקה ראשונה")
    assert reading is not None
    assert reading['previous_reading'] == test_meter['previous_reading']
    assert reading['current_reading'] == 250.5
    assert reading['consumption'] is not None
    assert reading['reading_status'] == 'submitted'

    # Verify meter state updated
    updated_meter = meter_service.get_meter(test_meter['period_meter_id'])
    assert updated_meter['work_status'] == 'in_progress'

    # Verify folder status updated
    updated_folder = folder_service.get_folder(test_folder['folder_id'])
    assert updated_folder['status'] == 'in_progress'

    # Approve reading
    reading_service.approve_reading(reading['reading_id'])
    approved = reading_service.get_reading(reading['reading_id'])
    assert approved['reading_status'] == 'approved'

    # Verify meter completed
    completed_meter = meter_service.get_meter(test_meter['period_meter_id'])
    assert completed_meter['work_status'] == 'completed'

    # Final summary
    test_period = test_data['test_period']
    summary = meter_service.get_period_status_summary(test_period['period_id'])
    assert summary['completed'] == 1
    assert summary['total'] == 10

    report("קריאה + צריכה + עדכון מצב + אישור + completed", True)
    print(f"    סיכום סופי: {summary}")

#  RUN ALL STEPS
def main():
    reset_counters()

    try:
        print("=" * 50)
        print("  Monim  - Happy Path Flow Test")
        print("=" * 50)

        print("\n ---שלב 1: יצירת לקוח ")
        run_step(test_step1_create_client, "שלב 1: יצירת לקוח")

        print("\n ---שלב 2: יצירת תקופות קריאה ")
        run_step(test_step2_create_periods, "שלב 2: יצירת תקופות")

        print("\n ---שלב 3: העלאת קובץ מקור ")
        run_step(test_step3_upload_source_file, "שלב 3: העלאת קובץ")

        print("\n ---שלב 4: עיבוד קובץ (פרסור אמיתי) ")
        run_step(test_step4_process_file, "שלב 4: עיבוד קובץ")

        print("\n ---שלב 5: יצירת תיקי עבודה ")
        run_step(test_step5_create_folders, "שלב 5: תיקי עבודה")

        print("\n ---שלב 6: שיוך קורא לתיק ")
        run_step(test_step6_assign_reader, "שלב 6: שיוך קורא")

        print("\n ---שלב 7: קריאה ואישור ")
        run_step(test_step7_create_reading, "שלב 7: קריאה ואישור")

        print("\n" + "=" * 50)
        print_summary()
        print("  Monim - הארכיטקטורה עובדת!")
        print("=" * 50)

    finally:
        cleanup()


if __name__ == "__main__":
    main()