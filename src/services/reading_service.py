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