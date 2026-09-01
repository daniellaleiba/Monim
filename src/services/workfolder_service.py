"""
Work Folder Service - Business Logic Layer

Manages the execution side of work division: creating folders from templates,
assigning them to readers, distributing meters into folders by walk_order,
and tracking folder progress through pending → assigned → in_progress → completed.
"""
 
from src.repositories.workfolder_repository import WorkFolderRepository
from src.repositories.reading_period_repository import ReadingPeriodRepository
from src.repositories.folder_template_repository import FolderTemplateRepository
from src.repositories.periodmeter_repository import PeriodMeterRepository
from src.repositories.reader_repository import ReaderRepository
from typing import List, Optional
from src.services.periodmeter_service import PeriodMeterService


class WorkFolderService:
    """
    Service for managing work folders - the execution layer of work division.
 
    WorkFolder is created from FolderTemplate for a specific period.
    It groups meters, is assigned to a reader, and tracks work progress.
 
    Responsibilities:
        - Create work folders from templates (single or all at once)
        - Assign readers to folders
        - Distribute meters into folders based on walk_order ranges
        - Track folder progress (total/completed meters)
        - Manage folder lifecycle (pending → assigned → in_progress → completed)
        - WorkFolder is execution; FolderTemplate is configuration.
    """
 
    def __init__(self):
        self.repo = WorkFolderRepository()
        self.period_repo = ReadingPeriodRepository()
        self.template_repo = FolderTemplateRepository()
        self.meter_repo = PeriodMeterRepository()
        self.reader_repo = ReaderRepository()
        self.meter_service = PeriodMeterService()

    
    # --- VALIDATION (Private):
 
    def _ensure_period_exists(self, period_id: int) -> dict:
        """Verify period exists and return it. Raises ValueError if not found."""
        period = self.period_repo.get_by_id(period_id)
        if not period:
            raise ValueError(f"תקופה {period_id} לא נמצאה במערכת")
        return period
 
    def _ensure_folder_exists(self, folder_id: int) -> dict:
        """Verify folder exists and return it. Raises ValueError if not found."""
        folder = self.repo.get_by_id(folder_id)
        if not folder:
            raise ValueError(f"תיק עבודה {folder_id} לא נמצא במערכת")
        return folder
 
    def _ensure_reader_exists(self, reader_id: int):
        """Verify reader exists. Raises ValueError if not found."""
        if not self.reader_repo.exists(reader_id):
            raise ValueError(f"קורא {reader_id} לא נמצא במערכת")
        
    # --- CREATE:
 
    def create_folder_from_template(self, period_id: int, template_id: int) -> dict:
        """
        Create a single work folder for a period based on a template.
 
        Flow:
            1. Verify period exists
            2. Verify template exists and belongs to same client
            3. Check no duplicate folder for this period + template
            4. Create folder
 
        Returns: The created work folder
        Raises: ValueError if validation fails
        """
        period = self._ensure_period_exists(period_id)
 
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise ValueError(f"תבנית {template_id} לא נמצאה במערכת")
 
        # Verify template belongs to same client as period
        if template['client_id'] != period['client_id']:
            raise ValueError("התבנית לא שייכת לאותו תאגיד של התקופה")
 
        # Check no duplicate
        if self.repo.exists_for_period_and_template(period_id, template_id):
            raise ValueError(
                f"כבר קיים תיק עבודה לתקופה זו מתבנית {template_id}"
            )
 
        return self.repo.create(period_id, template_id)
    
    def create_folders_for_period(self, period_id: int) -> List[dict]:
        """
        Create work folders for ALL templates of the client for this period.
        Skips templates that already have a folder for this period.
 
        Returns: List of created folders
        Raises: ValueError if period not found, or if the client has no folder
        templates defined at all
        """
        period = self._ensure_period_exists(period_id)
 
        templates = self.template_repo.list_by_client(period['client_id'])
        if not templates:
            raise ValueError("אין תבניות תיקים מוגדרות לתאגיד זה")
 
        created_folders = []
        for template in templates:
            # Skip if folder already exists for this template
            if self.repo.exists_for_period_and_template(period_id, template['template_id']):
                continue
 
            folder = self.repo.create(period_id, template['template_id'])
            created_folders.append(folder)
 
        return created_folders
    
    # --- READ:
 
    def get_folder(self, folder_id: int) -> Optional[dict]:
        """Get folder by ID, or None if not found"""
        return self.repo.get_by_id(folder_id)
 
    def get_period_folders(self, period_id: int) -> List[dict]:
        """Get all folders for a period"""
        self._ensure_period_exists(period_id)
        return self.repo.list_by_period(period_id)
 
    def get_reader_folders(self, reader_id: int) -> List[dict]:
        """Get all folders assigned to a reader"""
        self._ensure_reader_exists(reader_id)
        return self.repo.list_by_reader(reader_id)
    
    def list_open_folders_for_period(self, period_id: int) -> List[dict]:
        """
        Get all 'open' folders for a period - folders that can be assigned to a reader.
        Open = pending or assigned (not yet in_progress or completed).
        """
        self._ensure_period_exists(period_id)
        folders = self.repo.list_by_period(period_id)
        return [f for f in folders if f['status'] in ('pending', 'assigned')]
    
    def get_all_folders_overview(self) -> List[dict]:
        """Get all work folders across the system for the global overview screen."""
        return self.repo.list_all_with_details()

    # --- READER ASSIGNMENT:
 
    def assign_reader_to_folder(self, folder_id: int, reader_id: int) -> bool:
        """
        Assign a reader to a work folder.
        Updates folder status to 'assigned' if currently 'pending'.
        Promotes all folder meters with work_status 'assigned_to_folder' to 'assigned_to_reader'.

        Returns: True if assigned
        Raises: ValueError if folder/reader not found or reader not active
        """
        folder = self._ensure_folder_exists(folder_id)
        self._ensure_reader_exists(reader_id)
 
        # Check reader is active
        reader = self.reader_repo.get_by_id(reader_id)
        if not reader['active']:
            raise ValueError(f"קורא {reader_id} לא פעיל - לא ניתן לשייך אליו תיק")
        
         # Check folder is not already assigned to another reader
        if folder.get('assigned_to') and folder['assigned_to'] != reader_id:
            raise ValueError('תיק זה כבר משויך לקורא אחר')
    
        result = self.repo.assign_reader(folder_id, reader_id)

        # Update status to 'assigned' if currently 'pending'
        if result and folder['status'] == 'pending':
            self.repo.update_status(folder_id, 'assigned')
 
        # Promote all folder meters from 'assigned_to_folder' → 'assigned_to_reader'
        if result:
            folder_meters = self.meter_repo.list_by_folder(folder_id)
            for m in folder_meters:
                if m['work_status'] == 'assigned_to_folder':
                    self.meter_service.update_work_status(m['period_meter_id'], 'assigned_to_reader')
 
        return result
 
    def unassign_reader_from_folder(self, folder_id: int) -> bool:
        """
        Remove reader assignment from a folder.
        Resets status to 'pending'.
        Resets all 'assigned_to_reader' meters in the folder back to 'assigned_to_folder'.

        Returns: True if updated
        Raises: ValueError if folder not found
        """
        self._ensure_folder_exists(folder_id)
        self.repo.clear_reader_assignment(folder_id)
        self.repo.update_status(folder_id, 'pending')

        # Demote meters from 'assigned_to_reader' → 'assigned_to_folder'
        folder_meters = self.meter_repo.list_by_folder(folder_id)
        for m in folder_meters:
            if m['work_status'] == 'assigned_to_reader':
                self.meter_service.update_work_status(m['period_meter_id'], 'assigned_to_folder')
        return True
    
    # --- METER DISTRIBUTION:
 
    def distribute_meters_into_folders(self, period_id: int) -> dict:
        """
        Distribute all unassigned meters in a period into work folders
        based on their walk_order and the folder templates' walk_order ranges.

        Returns: dict with distribution summary
        Raises: ValueError if period not found or no folders exist
        """
        period = self._ensure_period_exists(period_id)

        folders = self.repo.list_by_period(period_id)
        if not folders:
            raise ValueError("אין תיקי עבודה לתקופה זו. צור תיקים קודם")

        unassigned = self.meter_repo.list_unassigned_by_period(period_id)
        if not unassigned:
            return {'assigned': 0, 'unmatched': 0, 'total_unassigned': 0}

        # Build folder lookup: load template ranges for each folder
        folder_ranges = []
        for folder in folders:
            template = self.template_repo.get_by_id(folder['template_id'])
            if template:
                folder_ranges.append({'folder_id': folder['folder_id'],
                    'walk_order_start': template['walk_order_start'], 'walk_order_end': template['walk_order_end'],})

        assigned_count = 0
        unmatched_count = 0

        for meter in unassigned:
            walk_order = meter.get('walk_order')

            if walk_order is None:
                unmatched_count += 1
                continue

            # Find matching folder by walk_order range
            matched_folder = None
            for fr in folder_ranges:
                if fr['walk_order_start'] <= walk_order <= fr['walk_order_end']:
                    matched_folder = fr
                    break

            if matched_folder:
                folder_obj = next((f for f in folders if f['folder_id'] == matched_folder['folder_id']), {})
                has_reader = bool(folder_obj.get('assigned_to'))
                self.meter_service.assign_meter_to_folder( meter['period_meter_id'], matched_folder['folder_id'], folder_has_reader=has_reader)
                assigned_count += 1
            else:
                unmatched_count += 1

        # Update folder counts
        for folder in folders:
            self.update_folder_progress(folder['folder_id'])

        return { 'assigned': assigned_count, 'unmatched': unmatched_count, 'total_unassigned': len(unassigned),}
    
    # --- PROGRESS TRACKING:
 
    def update_folder_progress(self, folder_id: int) -> dict:
        """
        Recalculate and update folder's meter counts from actual data.
        total_meters and completed_meters are cached fields, this syncs them.

        Note: uses an optimized COUNT query; if that query fails at runtime,
        falls back to fetching all folder meters and counting manually
 
        Returns: dict with updated counts
        Raises: ValueError if folder not found
        """
        self._ensure_folder_exists(folder_id)
 
        #How many meters are there in total? -Count from period_meters
        total = self.meter_repo.count_by_folder(folder_id)

        try:
            completed = self.meter_repo.count_by_work_status_and_folder(folder_id, 'completed')
        except Exception:
            # Fallback if DB query fails at runtime
            folder_meters = self.meter_repo.list_by_folder(folder_id)
            completed = sum(1 for m in folder_meters if m['work_status'] == 'completed')
 
        # Save the counts on the folder itself
        self.repo.update_counts(folder_id, total, completed)
 
        return {'total_meters': total, 'completed_meters': completed}
 
    def increment_folder_completion(self, folder_id: int) -> bool:
        """
        Increment completed_meters by 1.
        Called after a reading is completed for a meter in this folder.

        Note: callers that re-fetch the folder immediately after calling this
            will see the already-incremented count, don't add +1 again when
            comparing against total_meters (see reading_service.complete_meter_reading).
 
        Returns: True if updated
        Raises: ValueError if folder not found
        """
        self._ensure_folder_exists(folder_id)
        return self.repo.increment_completed_meters(folder_id)

    # --- STATUS MANAGEMENT:
 
    def start_folder_work(self, folder_id: int) -> bool:
        """
        Mark folder as in_progress (work has started).
        Only allowed from 'assigned' status.
 
        Returns: True if updated
        Raises: ValueError if folder not found or wrong status
        """
        folder = self._ensure_folder_exists(folder_id)
 
        if folder['status'] != 'assigned':
            raise ValueError(
                f"ניתן להתחיל עבודה רק על תיק בסטטוס 'assigned'. "
                f"סטטוס נוכחי: '{folder['status']}'"
            )
 
        return self.repo.update_status(folder_id, 'in_progress')
 
    def complete_folder(self, folder_id: int) -> bool:
        """
        Mark folder as completed (all work done).
        Only allowed from 'in_progress' status.
        Records completion timestamp.
 
        Returns: True if updated
        Raises: ValueError if folder not found or wrong status
        """
        folder = self._ensure_folder_exists(folder_id)
 
        if folder['status'] != 'in_progress':
            raise ValueError(
                f"ניתן להשלים רק תיק בסטטוס 'in_progress'. "
                f"סטטוס נוכחי: '{folder['status']}'"
            )
 
        return self.repo.mark_completed(folder_id)
    
    # --- DELETE:
 
    def delete_folder(self, folder_id: int) -> bool:
        """
        Delete a work folder.
        Automatically releases any meters assigned to this folder (folder_id reset to NULL) before deleting, the caller does not need to unassign meters first.

 
        Returns: True if deleted
        Raises: ValueError if folder not found
        """
        self._ensure_folder_exists(folder_id)
 
        # Release meters before delete
        self.meter_service.release_folder_meters(folder_id)
        return self.repo.delete(folder_id)

    def delete_period_folders(self, period_id: int) -> int:
        """
        Delete all folders for a period.
        Meters in each folder are released first (folder_id reset to NULL) via delete_folder.
 
        Returns: Number of deleted folders
        Raises: ValueError if period not found
        """
        self._ensure_period_exists(period_id)
        folders = self.repo.list_by_period(period_id)
        for folder in folders:
            self.delete_folder(folder['folder_id'])
        return len(folders)