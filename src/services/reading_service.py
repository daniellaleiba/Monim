"""
Reading Service - Business Logic Layer

Orchestrates the full lifecycle of a field reading: creates it, updates the
related period_meter's current state and work status, advances the owning
work folder's progress, and manages the review lifecycle
(submitted → approved / rejected / recheck).
"""
 
from src.repositories.reading_repository import ReadingRepository
from src.services.periodmeter_service import PeriodMeterService
from src.services.workfolder_service import WorkFolderService
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from psycopg2 import errors as pg_errors
 
# Exception types the mobile app can send (readings.exception_type CHECK)
VALID_EXCEPTION_TYPES = ('high', 'low', 'same', 'lower_than_previous')

class ReadingService:
    """
    Service for managing readings - field work results.
 
    A Reading is a single event: a reader went to a meter and recorded a value.
    Each reading updates the current state of the period_meter.
 
    Responsibilities:
        - Create readings with validation
        - Fetch previous_reading from period_meter
        - Calculate consumption
        - Update period_meter current state after reading
        - Update work folder progress after reading
        - Manage reading status lifecycle (submitted → approved / rejected / etc.)
        - Orchestrate between readings, meters, and folders
    """
 
    def __init__(self):
        self.repo = ReadingRepository()
        self.meter_service = PeriodMeterService()
        self.folder_service = WorkFolderService()

    # --- VALIDATION (Private):
 
    @staticmethod
    def _validate_current_reading(current_reading) -> bool:
        """Validate reading value: required, must be a number. Negative allowed (indicates meter issue)."""
        if current_reading is None:
            return False
        try:
            Decimal(str(current_reading))
            return True  # Any number is valid, including negative
        except (ValueError, TypeError):
            return False
 
    def _ensure_reading_exists(self, reading_id: int) -> dict:
        """Verify reading exists and return it. Raises ValueError if not found."""
        reading = self.repo.get_by_id(reading_id)
        if not reading:
            raise ValueError(f"קריאה {reading_id} לא נמצאה במערכת")
        return reading
 
    # --- CREATE:
 
    def create_reading(self, period_meter_id: int, reader_id: int, current_reading,
            fault_code: str = None, notes: str = None, transmitted_at=None) -> dict:
        """
        Create a new reading for a meter.
 
        This is the main orchestration function - it does several things:
            1. Validate inputs
            2. Fetch previous_reading from period_meter
            3. Calculate consumption
            4. Save the reading
            5. Update period_meter current state
            6. Update period_meter work status to 'in_progress' if needed
            7. Update work folder status to 'in_progress' if needed
            8. If fault_code present: mark meter as 'exception' (overrides step 6 status)

            Note: Folder completion increment happens later, in approve_reading → complete_meter_reading - not in this method.
            Note: Photo requirement for exception readings (fault_code present) is NOT enforced here yet.
 
        Args:
            period_meter_id: The meter being read
            reader_id: Who is performing the reading
            current_reading: The value read from the meter
            fault_code: Fault code if applicable
            notes: Reader notes
            transmitted_at: When transmitted from device
 
        Returns: The created reading record
        Raises: ValueError if validation fails
        """
        # Validate current reading value
        if not self._validate_current_reading(current_reading):
            raise ValueError("ערך קריאה לא תקין: חייב להיות מספר")
 
        # Get the meter - ensures it exists
        meter = self.meter_service.get_meter(period_meter_id)
        if not meter:
            raise ValueError(f"מונה {period_meter_id} לא נמצא במערכת")
 
        # Get previous_reading from the meter (snapshot)
        previous_reading = meter.get('previous_reading')
 
        # Calculate consumption
        consumption = None
        if previous_reading is not None and current_reading is not None:
            try:
                consumption = PeriodMeterService._calculate_consumption(current_reading, previous_reading)
            except (ValueError, TypeError):
                consumption = None
 
        # Save the reading
        reading = self.repo.create( period_meter_id=period_meter_id, reader_id=reader_id, previous_reading=previous_reading, current_reading=current_reading,
            consumption=consumption, fault_code=fault_code, notes=notes, transmitted_at=transmitted_at)
 
        # Update period_meter current state
        self.meter_service.apply_reading_to_current_state(period_meter_id, fault_code=fault_code, 
            current_reading = float(current_reading),)
 
        # Update work status if needed 
        if meter['work_status'] in ('new', 'assigned_to_folder', 'assigned_to_reader'):
            self.meter_service.update_work_status(period_meter_id, 'in_progress')
 
        # Handle folder-level updates
        folder_id = meter.get('folder_id')
        if folder_id:
            # Start folder work if it's the first reading
            folder = self.folder_service.get_folder(folder_id)
            if folder and folder['status'] == 'assigned':
                self.folder_service.start_folder_work(folder_id)
 
        # If meter has a fault or status that marks it as complete
        if  fault_code:
            self.meter_service.mark_exception(period_meter_id, fault_code, notes)
 
        return reading

    def receive_mobile_reading(self, period_meter_id: int, reader_id: int, version_id: str,
            is_no_reading: bool, current_reading=None, fault_code: str = None, notes: str = None,
            exception_type: str = None, first_attempt_reading=None, photo_missing: bool = False,
            read_at=None, received_at=None) -> dict:
        """
        Save one reading transmitted from the mobile app (WP3 transmit flow).

        Order matters: all checks first, then meter and folder updates, and the
        reading row itself LAST. That row (with version_id) is the "done" marker:
        if anything fails before it, a retransmission runs everything again, and
        every step before it is safe to repeat.

        Status rules:
            - verified exception (exception_type) or no-reading:
              meter 'exception', reading 'requires_review' (waits for the manager)
            - any other reading, with or without a fault code:
              meter 'completed' (folder progress advances), reading 'approved'

        Notes:
            - The reader's notes go to readings.notes only, never to manager_notes.
            - Each version is a full snapshot: the meter's fault code is set to this
              version's code, including clearing it.
            - Known limitation: a correction from a reading to a no-reading keeps the
              old current_reading on the meter (the reading log is correct).

        Returns: {'reading': the reading row, 'already_received': bool}
        Raises: ValueError if the data is invalid (nothing is written)
        """
        if not version_id:
            raise ValueError("חסר מזהה גרסה לקריאה")

        # 1. Already received this version? Nothing to do.
        existing = self.repo.get_by_version_id(version_id)
        if existing:
            return {'reading': existing, 'already_received': True}

        # 2. All checks, before any write
        meter = self.meter_service.get_meter(period_meter_id)
        if not meter:
            raise ValueError(f"מונה {period_meter_id} לא נמצא במערכת")

        if is_no_reading:
            if current_reading is not None:
                raise ValueError("אי-קריאה לא יכולה לכלול ערך קריאה")
            if not fault_code:
                raise ValueError("אי-קריאה חייבת קוד סיבה")
        elif not self._validate_current_reading(current_reading):
            raise ValueError("ערך קריאה לא תקין: חייב להיות מספר")

        if exception_type is not None:
            if exception_type not in VALID_EXCEPTION_TYPES:
                raise ValueError(f"סוג חריגה לא תקין: {exception_type}")
            if not fault_code:
                raise ValueError("חריגה מאומתת חייבת קוד תקלה")

        is_exception = is_no_reading or exception_type is not None
        received_at = received_at or datetime.now()
        previous_reading = meter.get('previous_reading')
        consumption = None
        if not is_no_reading and previous_reading is not None:
            consumption = PeriodMeterService._calculate_consumption(current_reading, previous_reading)

        # 3. Meter current state (repeating it overwrites with the same values)
        self.meter_service.apply_reading_to_current_state(
            period_meter_id,
            current_reading=None if is_no_reading else float(current_reading),
            reading_time=read_at)
        self.meter_service.update_fault_code(period_meter_id, fault_code)

        # 4. Folder: start work if it is still 'assigned' (normally the download did this)
        folder_id = meter.get('folder_id')
        if folder_id:
            folder = self.folder_service.get_folder(folder_id)
            if folder and folder['status'] == 'assigned':
                self.folder_service.start_folder_work(folder_id)

        # 5. Meter status
        if is_exception:
            self.meter_service.update_work_status(period_meter_id, 'exception')
            # A completed meter that became an exception: recount the folder's progress
            if meter['work_status'] == 'completed' and folder_id:
                self.folder_service.update_folder_progress(folder_id)
        else:
            # Meter 'completed' + folder progress +1, guarded against double counting
            self.complete_meter_reading(period_meter_id)

        # 6. The "done" marker: the reading row with version_id, written last
        try:
            reading = self.repo.create(
                period_meter_id=period_meter_id, reader_id=reader_id,
                previous_reading=previous_reading, current_reading=None if is_no_reading else current_reading,
                consumption=consumption, fault_code=fault_code, notes=notes,
                reading_status='requires_review' if is_exception else 'approved',
                transmitted_at=received_at, reading_time=read_at,
                is_no_reading=is_no_reading, first_attempt_reading=first_attempt_reading,
                exception_type=exception_type, photo_missing=photo_missing,
                version_id=version_id)
        except pg_errors.UniqueViolation:
            # The same version arrived twice at the same moment: the other request saved it
            return {'reading': self.repo.get_by_version_id(version_id), 'already_received': True}

        return {'reading': reading, 'already_received': False}
    
    def complete_meter_reading(self, period_meter_id: int) -> bool:
        """
        Mark a meter's reading work as completed.
        Called when the reading is approved and the meter is done.
 
        Updates meter work_status to 'completed' and increments folder count.
        (but only if the meter was NOT already 'completed', to avoid double-counting the same meter twice in the folder's completed_meters.)
        If this brings completed_meters to total_meters, auto-completes the folder (errors from complete_folder, e.g. wrong status are silently ignored).
 
        Returns: True if updated
        Raises: ValueError if meter not found
        """
        meter = self.meter_service.get_meter(period_meter_id)
        if not meter:
            raise ValueError(f"מונה {period_meter_id} לא נמצא")
        
        was_already_completed = meter['work_status'] == 'completed' # Checked *before* the change
 
        # Update meter status
        self.meter_service.update_work_status(period_meter_id, 'completed')
 
        # Increment folder completion
        folder_id = meter.get('folder_id')
        if folder_id and not was_already_completed:
            self.folder_service.increment_folder_completion(folder_id)
 
            # Check if all meters in folder are completed
            folder = self.folder_service.get_folder(folder_id)
            if folder and folder['completed_meters'] >= folder['total_meters']:
                try:
                    self.folder_service.complete_folder(folder_id)
                except ValueError:
                    pass  # Folder might not be in correct status
 
        return True
    
    # --- READ:
 
    def get_reading(self, reading_id: int) -> Optional[dict]:
        """Get single reading by ID"""
        return self.repo.get_by_id(reading_id)
 
    def get_meter_readings(self, period_meter_id: int) -> List[dict]:
        """Get all readings for a meter (newest first)"""
        return self.repo.list_by_period_meter(period_meter_id)
 
    def get_latest_meter_reading(self, period_meter_id: int) -> Optional[dict]:
        """Get the most recent reading for a meter"""
        return self.repo.get_latest_by_period_meter(period_meter_id)
 
    def get_reader_readings(self, reader_id: int) -> List[dict]:
        """Get all readings performed by a reader"""
        return self.repo.list_by_reader(reader_id)
 
    def get_period_readings(self, period_id: int) -> List[dict]:
        """Get all readings for a period"""
        return self.repo.list_by_period(period_id)
 
    def get_readings_for_review(self) -> List[dict]:
        """Get all readings that need review"""
        return self.repo.list_by_status('requires_review')
    
    # --- STATUS MANAGEMENT:
 
    def mark_requires_review(self, reading_id: int) -> bool:
        """
        Flag a reading for manager review.
        Typically called when consumption is abnormal or fault detected.
        """
        self._ensure_reading_exists(reading_id)
        return self.repo.update_status(reading_id, 'requires_review')
 
    def approve_reading(self, reading_id: int) -> bool:
        """
        Approve a reading - confirms it's valid.
        After approval, the meter can be marked as completed.
 
        Returns: True if updated
        Raises: ValueError if reading not found or not in reviewable status

        TODO: Exception readings (fault_code present) should require at least one attached photo before approval. 
        PhotoService.validate_photo_requirement already exists for this but is not yet called here - deferred to the
        field-reader mobile app phase, when the photo upload flow is built.
        """
        reading = self._ensure_reading_exists(reading_id)
 
        if reading['reading_status'] not in ('submitted', 'requires_review'):
            raise ValueError(
                f"ניתן לאשר רק קריאות בסטטוס 'submitted' או 'requires_review'. "
                f"סטטוס נוכחי: '{reading['reading_status']}'")
 
        self.repo.update_status(reading_id, 'approved')
 
        # Complete the meter reading
        self.complete_meter_reading(reading['period_meter_id'])
 
        return True
 
    def reject_reading(self, reading_id: int) -> bool:
        """
        Reject a reading - it's invalid, needs to be re-done.
        Resets the meter's work_status back to 'in_progress' so it appears again as pending work (a new reading is expected from the reader).
 
        Returns: True if updated
        Raises: ValueError if reading not found or not in reviewable status
        """
        reading = self._ensure_reading_exists(reading_id)
 
        if reading['reading_status'] not in ('submitted', 'requires_review'):
            raise ValueError( f"ניתן לדחות רק קריאות בסטטוס 'submitted' או 'requires_review'. "
                f"סטטוס נוכחי: '{reading['reading_status']}'" )
 
        self.repo.update_status(reading_id, 'rejected')
 
        # Mark meter for recheck
        self.meter_service.update_work_status(reading['period_meter_id'], 'in_progress')
 
        return True
    
    def request_recheck(self, reading_id: int) -> bool:
        """
        Request a recheck - send the reader back to re-read this meter.
        Keeps the meter's work_status at 'in_progress' so it stays on the reader's list.
 
        Returns: True if updated
        Raises: ValueError if reading not found
        """
        reading = self._ensure_reading_exists(reading_id)
        self.repo.update_status(reading_id, 'recheck')
 
        # Keep meter in_progress so it stays on the reader's list
        self.meter_service.update_work_status(reading['period_meter_id'], 'in_progress')
 
        return True
    
    # --- COUNTS:
 
    def count_meter_readings(self, period_meter_id: int) -> int:
        """Count readings for a meter"""
        return self.repo.count_by_period_meter(period_meter_id)
 
    def count_reader_readings(self, reader_id: int) -> int:
        """Count readings by a reader"""
        return self.repo.count_by_reader(reader_id)
 
    def count_pending_reviews(self) -> int:
        """Count readings waiting for review"""
        return self.repo.count_by_status('requires_review')
    
    # --- DELETE:
    def delete_reading(self, reading_id: int) -> bool:
        """
        Delete a reading.
        CASCADE will remove related photos.

        Returns: True if deleted
        Raises: ValueError if reading not found
        """
        self._ensure_reading_exists(reading_id)
        return self.repo.delete(reading_id)