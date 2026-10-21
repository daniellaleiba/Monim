"""
Period Meter Service - Business Logic Layer

Manages PeriodMeter: the core entity of the system: a meter's state within one reading period. 
    Creates meters from parsed source files, assigns them to work folders, tracks work status, applies readings to current state,
    calculates estimates for stopped/missing meters, and delegates shared-consumption writes to the repository.
"""
 
from src.repositories.periodmeter_repository import PeriodMeterRepository
from src.repositories.reading_period_repository import ReadingPeriodRepository
from src.repositories.periodsourcefile_repository import PeriodSourceFileRepository
from src.repositories.workfolder_repository import WorkFolderRepository

from typing import List, Optional
 
import logging
logger = logging.getLogger(__name__)

 
class PeriodMeterService:
    """
    Service for managing period meters, the CORE entity of the system.
 
    A PeriodMeter is a single meter as it appears in a specific reading period.
    It holds both the imported base data and the current operational state.
 
    Responsibilities:
        - Create period meters from parsed source file rows
        - Create meters a reader found in the field (not in the source file)
        - Validate import data
        - Assign meters to work folders (with period matching)
        - Update current state after readings
        - Mark meters as exceptions
        - Compare with previous period
        - PeriodMeter holds CURRENT state. Reading history is in readings table.
    """
    def __init__(self):
        self.repo = PeriodMeterRepository()
        self.period_repo = ReadingPeriodRepository()
        self.source_file_repo = PeriodSourceFileRepository()
        self.folder_repo = WorkFolderRepository() 
 
    # --- VALIDATION (Private): 

    @staticmethod
    def _validate_meter_number(meter_number: str) -> bool:
        """Validate meter number: required, not empty"""
        return bool(meter_number and str(meter_number).strip())
 
    @staticmethod
    def _validate_row_number(row_number) -> bool:
        """Validate row number: must be positive integer"""
        return isinstance(row_number, int) and row_number > 0
 
    def _ensure_period_exists(self, period_id: int) -> dict:
        """Verify period exists and return it. Raises ValueError if not found."""
        period = self.period_repo.get_by_id(period_id)
        if not period:
            raise ValueError(f"תקופה {period_id} לא נמצאה במערכת")
        return period
 
    def _ensure_meter_exists(self, period_meter_id: int) -> dict:
        """Verify period meter exists and return it. Raises ValueError if not found."""
        meter = self.repo.get_by_id(period_meter_id)
        if not meter:
            raise ValueError(f"מונה {period_meter_id} לא נמצא במערכת")
        return meter
    
    def _ensure_folder_exists(self, folder_id: int) -> dict:
        """Verify folder exists and return it. Raises ValueError if not found."""
        folder = self.folder_repo.get_by_id(folder_id)
        if not folder:
            raise ValueError(f"תיק עבודה {folder_id} לא נמצא במערכת")
        return folder

    def _ensure_folder_matches_period(self, folder_id: int, period_id: int) -> dict:
        """Verify folder exists and belongs to the given period. Raises ValueError otherwise."""
        folder = self._ensure_folder_exists(folder_id)
        if folder['period_id'] != period_id:
            raise ValueError("תיק העבודה לא שייך לאותה תקופה של המונה")
        return folder
    
    # --- CREATE 
 
    def create_meters_from_parsed_rows(self, period_id: int, source_file_id: int, parsed_rows: List[dict]) -> int:
        """
        Create period meters from parsed and normalized source file rows.
 
        Flow:
            1. Validate period and source file exist
            2. Validate each row has required fields
            3. Bulk insert all rows
            4. Return count of created meters
 
        Args:
            period_id: Reading period ID
            source_file_id: Source file these rows came from
            parsed_rows: List of normalized dicts from parser.
                         Each dict must contain at least:
                         - row_number (int)
                         - meter_number (str)
                         Optional fields:
                         - customer_number, customer_name, address,
                           walk_order, previous_reading, installation_date, raw_data
 
        Returns: Number of meters created
        Raises: ValueError if validation fails
        """
        self._ensure_period_exists(period_id)
 
        # Verify source file exists and belongs to this period
        source_file = self.source_file_repo.get_by_id(source_file_id)
        if not source_file:
            raise ValueError(f"קובץ מקור {source_file_id} לא נמצא במערכת")
        if source_file['period_id'] != period_id:
            raise ValueError("קובץ המקור לא שייך לתקופה זו")
 
        if not parsed_rows:
            raise ValueError("אין שורות לטעינה")
 
        # Validate required fields in each row
        errors = []
        for i, row in enumerate(parsed_rows):
            row_num = row.get('row_number', i + 1)
            if not self._validate_row_number(row.get('row_number')):
                errors.append(f"שורה {row_num}: מספר שורה חסר או לא תקין")
            if not self._validate_meter_number(row.get('meter_number')):
                errors.append(f"שורה {row_num}: מספר מונה חסר")
 
        if errors:
            raise ValueError(
                f"נמצאו {len(errors)} שגיאות בנתונים:\n" +
                "\n".join(errors[:20])  # Show first 20 errors max
            )
 
        # Bulk insert
        count = self.repo.bulk_create(period_id, source_file_id, parsed_rows)
        return count

    def create_field_meter(self, period_id: int, folder_id: int, meter_number: str,
            customer_number: str = None, customer_name: str = None, address: str = None,
            walk_order: int = None) -> dict:
        """
        Create a meter a reader found in the field (it is not in the source file).
        It belongs to the reader's folder, has no source file or row number,
        and is marked added_in_field.

        Note: the caller must refresh the folder's meter counts afterwards
              (WorkFolderService.update_folder_progress). This service can't call it
              itself: WorkFolderService already imports this one (circular import).

        Returns: The created meter row
        Raises: ValueError if the folder is not in the period, the meter number is
                empty, or a meter with this number already exists in the period
        """
        self._ensure_period_exists(period_id)
        self._ensure_folder_matches_period(folder_id, period_id)

        if not self._validate_meter_number(meter_number):
            raise ValueError("מספר מונה חסר")
        meter_number = str(meter_number).strip()

        if self.repo.get_by_period_and_meter_number(period_id, meter_number):
            raise ValueError(f"מונה {meter_number} כבר קיים בתקופה")

        return self.repo.create_field_meter(
            period_id, folder_id, meter_number, customer_number=customer_number,
            customer_name=customer_name, address=address, walk_order=walk_order)
    
    # --- READ:
 
    def get_meter(self, period_meter_id: int) -> Optional[dict]:
        """Get single meter by ID, or None if not found"""
        return self.repo.get_by_id(period_meter_id)
 
    def get_meter_by_number(self, period_id: int, meter_number: str) -> Optional[dict]:
        """Get meter by period + meter number"""
        return self.repo.get_by_period_and_meter_number(period_id, meter_number)
 
    def get_period_meters(self, period_id: int) -> List[dict]:
        """Get all meters for a period, ordered by walk_order"""
        self._ensure_period_exists(period_id)
        return self.repo.list_by_period(period_id)
 
    def get_folder_meters(self, folder_id: int) -> List[dict]:
        """Get all meters assigned to a specific folder"""
        return self.repo.list_by_folder(folder_id)
 
    def get_unassigned_meters(self, period_id: int) -> List[dict]:
        """Get all meters in a period not yet assigned to a folder"""
        return self.repo.list_unassigned_by_period(period_id)
 
    def get_exceptions(self, period_id: int) -> List[dict]:
        """Get all meters in exception status for a period"""
        return self.repo.list_exceptions_by_period(period_id)
 
    def get_meters_by_status(self, period_id: int, work_status: str) -> List[dict]:
        """Get all meters in a period with a specific work status"""
        return self.repo.list_by_work_status(period_id, work_status)

    # --- COUNTS:
 
    def count_period_meters(self, period_id: int) -> int:
        """Count total meters in a period"""
        return self.repo.count_by_period(period_id)
 
    def count_unassigned(self, period_id: int) -> int:
        """Count meters not yet assigned to a folder"""
        return self.repo.count_unassigned_by_period(period_id)
 
    def get_period_status_summary(self, period_id: int) -> dict:
        """Get summary of meter statuses for a period - single DB query."""
        self._ensure_period_exists(period_id)
        return self.repo.get_status_summary(period_id)
    
    # --- FOLDER ASSIGNMENT:
 
    def assign_meter_to_folder(self, period_meter_id: int, folder_id: int,  folder_has_reader: bool = False) -> bool:
        """
        Assign a single meter to a work folder.
        Validates that the folder belongs to the same period as the meter.
 
        Returns: True if assigned
        Raises: ValueError if meter/folder not found or period mismatch
        """
        meter = self._ensure_meter_exists(period_meter_id)
        self._ensure_folder_matches_period(folder_id, meter['period_id'])
 
        result = self.repo.update_folder_assignment(period_meter_id, folder_id)
 
        # Update work status to 'assigned' only if folder has a reader
        if result and meter['work_status'] == 'new':
                new_status = 'assigned_to_reader' if folder_has_reader else 'assigned_to_folder'
                self.repo.update_work_status(period_meter_id, new_status)

        return result
 

    def assign_meters_to_folder(self, period_meter_ids: List[int], folder_id: int) -> int:
        """
        Assign multiple meters to a work folder.
        Validates that the folder exists and that each meter belongs to the
        same period as the folder — mismatched or missing meters are skipped
        (not raised), so one bad ID doesn't block the rest of the batch.

        Args:
            period_meter_ids: List of meter IDs to assign
            folder_id: Target folder ID

        Returns: Number of meters actually assigned (may be less than
                len(period_meter_ids) if some were skipped)
        Raises: ValueError if folder not found
        """
        if not period_meter_ids:
            return 0

        folder = self._ensure_folder_exists(folder_id)

        # Single query for all meters — replaces the old per-meter get_by_id loop
        meters = self.repo.get_by_ids(period_meter_ids)
        valid_meters = [m for m in meters if m['period_id'] == folder['period_id']]
        valid_ids = [m['period_meter_id'] for m in valid_meters]

        skipped = len(period_meter_ids) - len(valid_ids)
        if skipped:
            logger.warning(f"{skipped} מונים דולגו בשיוך לתיק {folder_id}: לא נמצאו או משויכים לתקופה אחרת")

        if not valid_ids:
            return 0

        count = self.repo.bulk_update_folder_assignment(valid_ids, folder_id)

        # Update work status for meters that were 'new' — reuses valid_meters,
        # no extra per-meter query needed
        for m in valid_meters:
            if m['work_status'] == 'new':
                self.repo.update_work_status(m['period_meter_id'], 'assigned_to_folder')

        return count

    # --- ESTIMATION
    @staticmethod
    def _calculate_consumption(current_reading, previous_reading):
        """
        Calculate consumption (current - previous reading), rounded to 3 decimal places.
        Returns None if either value is missing.
        """
        if current_reading is None or previous_reading is None:
            return None
        return round(float(current_reading) - float(previous_reading), 3)

    def calculate_estimate(self, period_meter_id: int, fault_code: str = None) -> dict:
        """
        Calculate estimated reading for a meter based on parallel period last year (q6).
        
        Returns dict with:
            - current_reading: the estimated reading value
            - previous_reading: the baseline
            - addon: the q6 diff (only relevant for stopped meter, fault_code='1')
            - is_stopped_meter: bool
            - q6_diff: the parallel period consumption

        Note: 
            hist_readings[5]/[6] correspond to ק5/ק6 in raw_data -- see the normalized-row format documented in src/parsers/base_parser.py
            (index 0 = current reading, 1-6 = ק1..ק6, one entry per prior period)
        
        Raises: ValueError if meter not found or no q6 data available
        """
        if not fault_code:
            raise ValueError('לא ניתן לבצע הערכה ללא קוד תקלה')

        meter = self._ensure_meter_exists(period_meter_id)
        
        raw = meter.get('raw_data') or {}
        hist = raw.get('hist_readings') or []
        
        if len(hist) < 7 or hist[5] is None or hist[6] is None:
            raise ValueError("אין נתוני קריאה מקבילה (ק.6) לביצוע הערכה")
        
        q6_diff = round(float(hist[5]) - float(hist[6]), 3)
        
        previous_reading = meter.get('previous_reading')
        if previous_reading is None:
            raise ValueError("אין קריאה קודמת למונה זה")
        
        previous_reading = float(previous_reading)
        is_stopped_meter = (fault_code == '1')
        
        if is_stopped_meter:
            current_reading = previous_reading
            addon = q6_diff
        else:
            current_reading = round(previous_reading + q6_diff, 3)
            addon = None
        
        return {
            'current_reading':  current_reading,
            'previous_reading': previous_reading,
            'addon':addon,
            'is_stopped_meter': is_stopped_meter,
            'q6_diff':q6_diff,
        }

    def bulk_estimate(self, period_id, folder_id=None):
        """
        Estimate all eligible meters in a period or folder in one batch.
        Skips meters that: have no fault code, fault_code='1', already estimated, or lack hist_readings.
        Args:
            period_id: The reading period
            folder_id: Optional - if provided, only estimates meters in this folder
        Returns:
            dict with keys: estimated, skipped, failed, updates
        """
        meters = self.get_folder_meters(folder_id) if folder_id else self.get_period_meters(period_id)
        
        updates = []
        failed = 0
        
        for m in meters:
            if (not m.get('current_fault_code') or 
                m.get('current_fault_code') == '1' or
                m.get('is_estimated') or
                not m.get('raw_data', {}).get('hist_readings')):
                continue
            try:
                result = self.calculate_estimate(m['period_meter_id'], m['current_fault_code'])
                consumption = self._calculate_consumption(result['current_reading'], m.get('previous_reading'))
                updates.append({
                    'period_meter_id': m['period_meter_id'],
                    'current_reading': result['current_reading'],
                    'consumption':     consumption,
                    'addon':           result.get('addon'),
                })
            except Exception:
                failed += 1
        
        estimated = self.repo.bulk_update_estimated(updates)
        return { 'estimated': estimated, 'skipped': len(meters) - len(updates) - failed, 'failed': failed,
            'updates': [
                {
                    'period_meter_id': u['period_meter_id'],
                    'current_reading': u['current_reading'],
                    'consumption':     u['consumption'],
                }
                for u in updates
            ]
        }

    # --- SHARED CONSUMPTION (delegated writes) ---
    def reset_shared_consumption_by_prefix(self, period_id: int, building_key: str) -> None:
        """Reset shared_consumption to NULL for all meters in a building (by meter_id prefix)."""
        self.repo.reset_shared_consumption_by_prefix(period_id, building_key)

    def bulk_update_shared_consumption(self, updates: list) -> int:
        """Bulk update shared_consumption for multiple meters in one transaction."""
        return self.repo.bulk_update_shared_consumption(updates)

    # --- WORK STATUS ---
    def update_work_status(self, period_meter_id: int, work_status: str) -> bool:
        """
        Update work status of a meter.

        Note: does NOT touch anything else, folder completed_meters count is incremented separately, by WorkFolderService.increment_folder_completion(),
        called from ReadingService.complete_meter_reading().

        Returns: True if updated
        Raises: ValueError if meter not found or invalid status
        """
        valid_statuses = ('new', 'assigned_to_folder', 'assigned_to_reader', 'in_progress', 'completed', 'exception',  'missing_info')
        if work_status not in valid_statuses:
            raise ValueError(f"סטטוס '{work_status}' לא תקין. "
                f"סטטוסים מותרים: {', '.join(valid_statuses)}")
        
        meter = self._ensure_meter_exists(period_meter_id)
        result = self.repo.update_work_status(period_meter_id, work_status)

        return result

    def update_fault_code(self, period_meter_id: int, fault_code: str | None):
        """
        Update the meter's current_fault_code field.

        Returns: True if updated
        """
        return self.repo.update_fault_code(period_meter_id, fault_code)

    def update_manager_notes(self, period_meter_id: int, manager_notes: str | None) -> bool:
        """
        Set the manager's notes on a meter (they are sent to the reader's app on download).
        Empty or whitespace-only text clears the notes (stored as NULL).

        Returns: True if updated
        Raises: ValueError if meter not found
        """
        self._ensure_meter_exists(period_meter_id)
        notes = manager_notes.strip() if manager_notes else None
        return self.repo.update_manager_notes(period_meter_id, notes or None)
    
    # --- CURRENT STATE (after reading / manager review):
    def apply_reading_to_current_state(self, period_meter_id: int, fault_code: str = None, 
             current_reading: float = None, manager_notes: str = None, addon: float = None, reading_time=None, is_estimated=False) -> bool:
        """
        Update meter's current state after a new reading is received.
        Called by ReadingService after a reading is created, or by manager review.

        If current_reading is provided and the meter has a previous_reading,
        consumption is calculated automatically (current - previous), the caller does not need to compute it.

        Args:
            period_meter_id: The meter to update
            fault_code: Fault code, if any
            current_reading: New reading value (consumption is derived from this)
            manager_notes: Free-text notes
            addon: Extra amount added to the reading (stopped-meter estimation, see calculate_estimate)
            reading_time: Timestamp of the reading
            is_estimated: Whether this value came from calculate_estimate rather than a field reading
        
        Returns: True if updated
        Raises: ValueError if meter not found
        """
        meter = self._ensure_meter_exists(period_meter_id)

        consumption = None
        if current_reading is not None:
            prev = meter.get('previous_reading')
            if prev is not None:
                consumption = self._calculate_consumption(current_reading, meter.get('previous_reading'))

        return self.repo.update_current_state(
        period_meter_id, fault_code = fault_code, manager_notes = manager_notes,
        current_reading = current_reading, consumption = consumption,
        addon = addon, reading_time = reading_time, is_estimated=is_estimated)
 
    def mark_exception(self, period_meter_id: int, fault_code: str, notes: str = None) -> bool:
        """
        Mark a meter as exception, needing special attention.
        Sets work_status to 'exception' and updates current_state's fault_code and manager_notes only (current_reading/consumption are left untouched).

        Returns: True if the work_status update succeeded
        Raises: ValueError if meter not found
        """
        self._ensure_meter_exists(period_meter_id)
 
        result = self.update_work_status(period_meter_id, 'exception')
        self.repo.update_current_state(period_meter_id, fault_code=fault_code, manager_notes=notes)
        return result

    # --- DELETE ---
    def delete_meters_by_source_file(self, source_file_id: int) -> int:
        """
        Delete all meters created from a specific source file.
        Used when replacing a file or retrying failed processing.
 
        Returns: Number of deleted meters
        """
        return self.repo.delete_by_source_file(source_file_id)
    
    def release_folder_meters(self, folder_id: int) -> int:
        """
        Release all meters from a folder.
        Resets folder_id to NULL. Also resets work_status back to 'new'; except meters already 'completed', which keep their status.
        Used when deleting a work folder, meters remain in the period, just unassigned.

        Returns: Number of meters released
        """
        return self.repo.release_folder_meters(folder_id)