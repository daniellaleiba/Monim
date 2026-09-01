"""
Monim : Demo Run
Full end-to-end flow demonstrating the entire system.

Flow:
    1. Create client (water corporation)
    2. Create reader (field worker)
    3. Create reading period
    4. Upload source file
    5. Process file (parser → period_meters)
    6. Create folder templates (work division)
    7. Create work folders for period
    8. Distribute meters into folders
    9. Assign reader to folder
    10. Create readings for 3 meters, intentionally left at different stages (assigned_to_reader / in_progress / completed) 
        to show a realistic mix of work_status values, not just one meter racing to completion
    11. Approve only the third meter's reading (→ completed)
    12. Print summary

Uses monim_v2_test DB. Cleans up after run.
(Can be used as a portfolio demo, shows the system is alive without UI).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Use test DB
os.environ['DB_NAME'] = 'monim_v2_test'

from src.services.client_service import ClientService
from src.services.reader_service import ReaderService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.workfolder_service import WorkFolderService
from src.services.reading_service import ReadingService
from tests.test_helpers import cleanup

# --- Services ---
client_service = ClientService()
reader_service = ReaderService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
reading_service = ReadingService()

# --- Sample file ---
SAMPLE_FILE = os.path.join(os.path.dirname(__file__), '..', 'tests',
                           'parsing_tests', 'test_data', 'netanya_sample.xlsx')


def main():
    print("=" * 60)
    print("  Monim V2 - Demo Run")
    print("  מערכת ניהול קריאות מוני מים")
    print("=" * 60)

    try:
        #  1. CREATE CLIENT
        print("\n=== שלב 1: יצירת תאגיד ===")
        client = client_service.create_client("מי נתניה", "500000001")
        print(f"  ✔ תאגיד נוצר: {client['name']} (ID: {client['client_id']})")

        #  2. CREATE READER
        print("\n=== שלב 2: יצירת קורא שטח ===")
        reader = reader_service.create_reader(
            name="דוד כהן", username="david_k",
            password_hash="hashed_password_123", phone="0501234567")
        print(f"  ✔ קורא נוצר: {reader['name']} (ID: {reader['reader_id']})")

        #  3. CREATE READING PERIOD
        print("\n=== שלב 3: יצירת תקופת קריאה ===")
        period = period_service.create_period(client['client_id'], 2026, 2)
        print(f"  ✔ תקופה נוצרה: {period['year']} / תקופה {period['period_number']} (מרץ-אפריל)")
        print(f"    סטטוס: {period['status']}")

        #  4. UPLOAD SOURCE FILE
        print("\n=== שלב 4: העלאת קובץ אב ===")
        source_file = source_file_service.upload_period_file(
            period_id=period['period_id'], original_filename="netanya_period_2.xlsx",
            file_type="netanya_format", uploaded_by="מנהל עבודה",
            file_path=SAMPLE_FILE)
        print(f"  ✔ קובץ הועלה: {source_file['original_filename']}")
        print(f"    סטטוס עיבוד: {source_file['processing_status']}")

        # Check period status updated
        period = period_service.get_period(period['period_id'])
        print(f"    סטטוס תקופה: {period['status']}")

        #  5. PROCESS FILE
        print("\n=== שלב 5: עיבוד קובץ (parser → מונים) ===")
        result = source_file_service.process_uploaded_file(source_file['source_file_id'])
        print(f"  ✔ קובץ עובד בהצלחה!")
        print(f"    סטטוס עיבוד: {result['processing_status']}")
        print(f"    שורות שיובאו: {result['rows_count']}")

        if result['error_message']:
            print(f"    הערות: {result['error_message'][:100]}...")

        # Show meter summary
        summary = meter_service.get_period_status_summary(period['period_id'])
        print(f"    סה\"כ מונים: {summary['total']}")
        print(f"    מונים חדשים (new): {summary['new']}")

        period = period_service.get_period(period['period_id'])
        print(f"    סטטוס תקופה: {period['status']}")

        #  6. CREATE FOLDER TEMPLATES
        print("\n=== שלב 6: הגדרת תבניות תיקים ===")

        # The sample data has walk_orders:
        # 105035029, 1010000000-1010007000, 1010414100
        # We'll create 3 templates to cover these ranges

        template1 = template_service.create_template( client_id=client['client_id'], folder_number=1,
            folder_name="אזור מרכז", walk_order_start=100000000, walk_order_end=199999999)
        print(f"  ✔ תבנית 1: {template1['folder_name']} (סדר הליכה {template1['walk_order_start']}-{template1['walk_order_end']})")

        template2 = template_service.create_template( client_id=client['client_id'], folder_number=2,
            folder_name="אזור צפון", walk_order_start=1010000000, walk_order_end=1010099999)
        print(f"  ✔ תבנית 2: {template2['folder_name']} (סדר הליכה {template2['walk_order_start']}-{template2['walk_order_end']})")

        template3 = template_service.create_template( client_id=client['client_id'], folder_number=3,
            folder_name="אזור דרום", walk_order_start=1010100000,  walk_order_end=1010999999)
        print(f"  ✔ תבנית 3: {template3['folder_name']} (סדר הליכה {template3['walk_order_start']}-{template3['walk_order_end']})")

        #  7. CREATE WORK FOLDERS
        print("\n=== שלב 7: יצירת תיקי עבודה לתקופה ===")
        folders = folder_service.create_folders_for_period(period['period_id'])
        print(f"  ✔ נוצרו {len(folders)} תיקי עבודה")
        for folder in folders:
            print(f"    תיק {folder['folder_id']}: תבנית {folder['template_id']}, סטטוס: {folder['status']}")

        #  8. DISTRIBUTE METERS INTO FOLDERS
        print("\n=== שלב 8: חלוקת מונים לתיקים ===")
        dist = folder_service.distribute_meters_into_folders(period['period_id'])
        print(f"  ✔ חלוקה הושלמה!")
        print(f"    שויכו לתיקים: {dist['assigned']}")
        print(f"    לא שויכו (ללא סדר הליכה): {dist['unmatched']}")
        print(f"    סה\"כ לא משויכים לפני: {dist['total_unassigned']}")

        # Show folder details
        period_folders = folder_service.get_period_folders(period['period_id'])
        for folder in period_folders:
            print(f"    תיק {folder['folder_id']}: {folder['total_meters']} מונים, סטטוס: {folder['status']}")

        #  9. ASSIGN READER TO FOLDER
        print("\n=== שלב 9: שיוך קורא לתיק ===")

        # Find the folder with the most meters, so we have room to leave
        # several meters at different work-status stages below
        target_folder = max(period_folders, key=lambda f: f['total_meters'], default=None)
        if target_folder and target_folder['total_meters'] == 0:
            target_folder = None

        if target_folder:
            folder_service.assign_reader_to_folder(target_folder['folder_id'], reader['reader_id'])
            updated_folder = folder_service.get_folder(target_folder['folder_id'])
            print(f"  ✔ הקורא {reader['name']} שויך לתיק {target_folder['folder_id']}")
            print(f"    סטטוס תיק: {updated_folder['status']}")
            print(f"    מונים בתיק: {updated_folder['total_meters']}")
        else:
            print("  ⚠ אין תיקים עם מונים לשיוך")

        #  10. CREATE READINGS: leave meters at different stages on purpose,
        #      so the final summary shows a realistic mix of work_status values
        print("\n=== שלב 10: ביצוע קריאות בשטח (מצבים שונים) ===")

        folder_meters = meter_service.get_folder_meters(target_folder['folder_id'])
        reading = None
        test_meter = None

        if len(folder_meters) >= 1:
            meter_a = folder_meters[0]
            print(f"\n  מונה א' ({meter_a['meter_number']}): נשאר assigned_to_reader ; טרם בוצעה קריאה בשטח")

        if len(folder_meters) >= 2:
            meter_b = folder_meters[1]
            previous_b = meter_b.get('previous_reading', 0)
            current_b = float(previous_b) + 15 if previous_b else 50
            reading_b = reading_service.create_reading(
                period_meter_id=meter_b['period_meter_id'], reader_id=reader['reader_id'],
                current_reading=current_b, notes="קריאה בוצעה, טרם אושרה")
            updated_b = meter_service.get_meter(meter_b['period_meter_id'])
            print(f"\n  מונה ב' ({meter_b['meter_number']}): קריאה נשמרה (ID: {reading_b['reading_id']}), סטטוס: {updated_b['work_status']} - ממתין לאישור מנהל")

        if len(folder_meters) >= 3:
            meter_c = folder_meters[2]
            test_meter = meter_c
            previous_c = meter_c.get('previous_reading', 0)
            current_c = float(previous_c) + 32 if previous_c else 100

            print(f"\n  מונה ג' ({meter_c['meter_number']}):")
            print(f"    כתובת: {meter_c['address']}")
            print(f"    קריאה קודמת: {previous_c}")
            print(f"    קריאה נוכחית: {current_c}")

            reading = reading_service.create_reading(
                period_meter_id=meter_c['period_meter_id'], reader_id=reader['reader_id'],
                current_reading=current_c, notes="מונה תקין ונגיש")
            consumption = reading.get('consumption', 'N/A')
            print(f"    ✔ קריאה נשמרה! (ID: {reading['reading_id']})")
            print(f"    צריכה: {consumption}")
            print(f"    סטטוס קריאה: {reading['reading_status']}")

            updated_meter = meter_service.get_meter(meter_c['period_meter_id'])
            print(f"    סטטוס מונה: {updated_meter['work_status']}")

        #  11. APPROVE READING (only meter C goes all the way to 'completed'; meters A and B are intentionally left at earlier stages)
        print("\n=== שלב 11: אישור קריאה (מונה ג') ===")
        if reading and test_meter:
            reading_service.approve_reading(reading['reading_id'])

            approved = reading_service.get_reading(reading['reading_id'])
            print(f"  ✔ קריאה אושרה!")
            print(f"    סטטוס קריאה: {approved['reading_status']}")

            completed_meter = meter_service.get_meter(test_meter['period_meter_id'])
            print(f"    סטטוס מונה: {completed_meter['work_status']}")
        else:
            print("  ⚠ לא נוצרה קריאה למונה ג' (פחות מ-3 מונים בתיק)")

        #  12. SUMMARY
        print("\n" + "=" * 60)
        print("  סיכום")
        print("=" * 60)

        final_summary = meter_service.get_period_status_summary(period['period_id'])
        print(f"\n  תאגיד: {client['name']}")
        print(f"  תקופה: {period['year']} / תקופה {period['period_number']}")
        print(f"\n  --- מונים ---")
        print(f"  סה\"כ:       {final_summary['total']}")
        print(f"  חדשים:      {final_summary['new']}")
        print(f"  שויכו לתיק:   {final_summary['assigned_to_folder']}")
        print(f"  שויכו לקורא:  {final_summary['assigned_to_reader']}")
        print(f"  בביצוע:     {final_summary['in_progress']}")
        print(f"  הושלמו:     {final_summary['completed']}")
        print(f"  חריגים:     {final_summary['exception']}")
        print(f"  חסר מידע:    {final_summary['missing_info']}")

        # Folder summary
        print(f"\n  --- תיקים ---")
        final_folders = folder_service.get_period_folders(period['period_id'])
        for folder in final_folders:
            status_icon = "✔" if folder['status'] == 'completed' else "▶" if folder['status'] == 'in_progress' else "○"
            print(f"  {status_icon} תיק {folder['folder_id']}: {folder['completed_meters']}/{folder['total_meters']} הושלמו, סטטוס: {folder['status']}")

        print(f"\n  --- קורא ---")
        print(f"  {reader['name']}: ביצע קריאות")

        print(f"\n" + "=" * 60)
        print("  ✔ המערכת חיה ועובדת מקצה לקצה!")
        print("=" * 60)

    finally:
        cleanup()


if __name__ == "__main__":
    main()