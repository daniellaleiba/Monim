"""
Shared utilities for route blueprints, imported once at app startup, not per-request:
- Service instances (singletons: one instance per service, shared across all blueprints)
- Hebrew label constants (status → display text, for templates)
- Generic helper functions
"""

from datetime import date, datetime
from decimal import Decimal

# --- Service instances ---
# Imported once and shared across all blueprints
from src.services.client_service import ClientService
from src.services.reading_period_service import ReadingPeriodService
from src.services.periodsourcefile_service import PeriodSourceFileService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.workfolder_service import WorkFolderService
from src.services.reader_service import ReaderService
from src.services.fault_code_service import FaultCodeService
from src.services.reading_service import ReadingService
from src.services.photo_service import PhotoService
from src.services.shared_consumption_service import SharedConsumptionService
from src.services.mobile_service import MobileService

client_service = ClientService()
period_service = ReadingPeriodService()
source_file_service = PeriodSourceFileService()
meter_service = PeriodMeterService()
template_service = FolderTemplateService()
folder_service = WorkFolderService()
reader_service = ReaderService()
fault_code_service = FaultCodeService()
reading_service = ReadingService()
photo_service   = PhotoService()
shared_consumption_service = SharedConsumptionService()
mobile_service = MobileService()


# --- Upload directory ---
import os
UPLOAD_DIR = os.path.join('static', 'uploads')


# --- Hebrew labels ---
PERIOD_MONTHS_HE = {
    1: "ינואר - פברואר",
    2: "מרץ - אפריל",
    3: "מאי - יוני",
    4: "יולי - אוגוסט",
    5: "ספטמבר - אוקטובר",
    6: "נובמבר - דצמבר",
}


PERIOD_STATUS_HE = {
    'pending': 'ממתין',
    'file_received': 'קובץ התקבל',
    'active': 'פעיל',
    'completed': 'הושלם',
    'skipped': 'דולג',
}

FILE_STATUS_HE = {
    'pending': 'ממתין',
    'success': 'עובד בהצלחה',
    'partial': 'עובד חלקית',
    'error':'שגיאה',
}

WORK_STATUS_HE = {
    'new': 'חדש',
    'assigned_to_folder': 'שויך לתיק',
    'assigned_to_reader': 'שויך לקורא',
    'in_progress':'בביצוע',
    'completed': 'הושלם',
    'exception': 'חריג',
    'missing_info':  'חסר מידע',
}

FOLDER_STATUS_HE = {
    'pending': 'ממתין',
    'assigned': 'משויך',
    'in_progress': 'בביצוע',
    'completed': 'הושלם',
}


# --- Generic helpers ---
def to_json_safe(obj):
    """ממיר RealDictRow לdict סריאלי ל-JSON (מטפל ב-date/Decimal)."""
    if obj is None:
        return None
    result = {}
    for k, v in obj.items():
        if isinstance(v, (date, datetime)):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result