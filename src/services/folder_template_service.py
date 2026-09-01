"""
Folder Template Service - Business Logic Layer


Manages FolderTemplate: the fixed walk-order configuration per client that work folders are generated from each period. 
Enforces uniqueness (folder number, folder name) and prevents walk-order range overlaps within a client.
"""
 
from src.repositories.folder_template_repository import FolderTemplateRepository
from src.repositories.client_repository import ClientRepository
from typing import List, Optional
from src.services.workfolder_service import WorkFolderService
 
 
class FolderTemplateService:
    """
    Service for managing folder templates (work division configuration).
 
    Responsibilities:
        - Validate template creation and updates
        - Prevent walk-order range overlaps
        - Prevent duplicate folder numbers / names per client
        - Ensure template belongs to the correct client
        - FolderTemplate is configuration - actual work folders
          are created by WorkFolderService.
    """
    
    def __init__(self):
        self.repo = FolderTemplateRepository()
        self.client_repo = ClientRepository()
        self.workfolder_service = WorkFolderService() 
 
    # --- VALIDATION (Private):

    @staticmethod
    def _validate_folder_name(name: str) -> bool:
        """Validate folder name: required, at least 2 characters"""
        if not name or not name.strip():
            return False
        return len(name.strip()) >= 2
 
    @staticmethod
    def _validate_folder_number(folder_number: int) -> bool:
        """Validate folder number: must be positive"""
        return isinstance(folder_number, int) and folder_number > 0
 
    @staticmethod
    def _validate_walk_order_range(walk_order_start: int, walk_order_end: int) -> bool:
        """Validate walk order range: start must be less than end, both positive"""
        if not isinstance(walk_order_start, int) or not isinstance(walk_order_end, int):
            return False
        return walk_order_start > 0 and walk_order_end > 0 and walk_order_start < walk_order_end
    
    # --- UTILITIES (Private helpers):
 
    def _safe_prepare_folder_name(self, client_id: int, folder_name: str, exclude_template_id: int = None) -> str:
        """
        Validate format, normalize, and check uniqueness of folder name per client.
        Used by both create and update flows.
 
        Returns: Cleaned name ready for DB
        Raises: ValueError if invalid or duplicate
        """
        if not self._validate_folder_name(folder_name):
            raise ValueError("שם תיק לא תקין: חייב להיות לפחות 2 תווים")
 
        folder_name = folder_name.strip()
 
        if self.repo.name_exists(client_id, folder_name, exclude_template_id=exclude_template_id):
            raise ValueError(f"שם תיק '{folder_name}' כבר קיים אצל תאגיד זה")
 
        return folder_name
    
    def _safe_prepare_folder_number(self, client_id: int, folder_number: int, exclude_template_id: int = None) -> int:
        """
        Validate and check uniqueness of folder number per client.
        Used by both create and update flows.
 
        Returns: Validated folder number
        Raises: ValueError if invalid or duplicate
        """
        if not self._validate_folder_number(folder_number):
            raise ValueError("מספר תיק לא תקין: חייב להיות מספר חיובי")
 
        if self.repo.folder_number_exists(client_id, folder_number, exclude_template_id=exclude_template_id):
            raise ValueError(f"מספר תיק {folder_number} כבר קיים אצל תאגיד זה")
 
        return folder_number
    
    def _safe_prepare_walk_order_range(self, client_id: int, walk_order_start: int, walk_order_end: int, exclude_template_id: int = None) -> tuple:
        """
        Validate range and check for overlaps with existing templates.
        Used by both create and update flows.
 
        Returns: (walk_order_start, walk_order_end) validated
        Raises: ValueError if invalid or overlapping
        """
        if not self._validate_walk_order_range(walk_order_start, walk_order_end):
            raise ValueError("טווח סדר הליכה לא תקין: חייב להיות חיובי, וההתחלה לפני הסוף")
 
        overlaps = self.repo.list_overlapping_templates(client_id, walk_order_start, walk_order_end, exclude_template_id=exclude_template_id)
        if overlaps:
            conflicting_names = [t['folder_name'] or f"תיק {t['folder_number']}" for t in overlaps]
            raise ValueError(
                f"טווח סדר הליכה {walk_order_start}-{walk_order_end} "
                f"חופף עם: {', '.join(conflicting_names)}")
 
        return walk_order_start, walk_order_end
    
    def _ensure_client_exists(self, client_id: int):
        """
        Verify that the client exists.
        Raises: ValueError if client not found
        """
        if not self.client_repo.exists(client_id):
            raise ValueError(f"תאגיד {client_id} לא נמצא במערכת")
        
    # --- CREATE:

    def create_template(self, client_id: int, folder_number: int, folder_name: str,
                        walk_order_start: int, walk_order_end: int) -> dict:
        """
        Create new folder template with full validation.
 
        Flow:
                1. Verify client exists
                2. Validate and check uniqueness of folder number
                3. Auto-generate folder_name as "תיק {folder_number}" if not provided
                4. Validate and check uniqueness of folder name
                5. Validate walk order range and check overlaps
                6. Save to DB
 
        Returns: The created template (full row)
        Raises: ValueError if validation fails
        """
        self._ensure_client_exists(client_id)
        folder_number = self._safe_prepare_folder_number(client_id, folder_number)
        
        # Auto-generate folder name if not provided
        if not folder_name or not folder_name.strip():
            folder_name = f"תיק {folder_number}"
        
        folder_name = self._safe_prepare_folder_name(client_id, folder_name)
        walk_order_start, walk_order_end = self._safe_prepare_walk_order_range(client_id, walk_order_start, walk_order_end)
 
        return self.repo.create(client_id, folder_number, folder_name, walk_order_start, walk_order_end)
    
    # --- READ:
 
    def get_template(self, template_id: int) -> Optional[dict]:
        """Get template by ID, or None if not found"""
        return self.repo.get_by_id(template_id)
 
    def get_client_templates(self, client_id: int) -> List[dict]:
        """
        Get all templates for a client, ordered by folder number.
        Raises: ValueError if client not found
        """
        self._ensure_client_exists(client_id)
        return self.repo.list_by_client(client_id)
 
    def count_client_templates(self, client_id: int) -> int:
        """Count templates for a client"""
        return self.repo.count_by_client(client_id)
    
    # --- UPDATE: 
 
    def update_template(self, template_id: int, folder_name: str = None, folder_number: int = None, walk_order_start: int = None, walk_order_end: int = None) -> bool:
        """
        Update template with validation.
 
        If only one of walk_order_start/walk_order_end is provided, the other keeps its current value. 
        The effective new range is still re-validated (range + overlap checks) against the template's existing values.
 
        Returns: True if updated, False if nothing to update
        Raises: ValueError if template not found or validation fails
        """
        template = self.repo.get_by_id(template_id)
        if not template:
            raise ValueError(f"תבנית {template_id} לא נמצאה במערכת")
 
        client_id = template['client_id']
        updates = {}
 
        if folder_name is not None:
            updates['folder_name'] = self._safe_prepare_folder_name( client_id, folder_name, exclude_template_id=template_id)
 
        if folder_number is not None:
            updates['folder_number'] = self._safe_prepare_folder_number( client_id, folder_number, exclude_template_id=template_id)
 
        # Walk order range:  must be updated together
        if walk_order_start is not None or walk_order_end is not None:
            # If only one provided, use existing value for the other
            new_start = walk_order_start if walk_order_start is not None else template['walk_order_start']
            new_end = walk_order_end if walk_order_end is not None else template['walk_order_end']
 
            new_start, new_end = self._safe_prepare_walk_order_range(client_id, new_start, new_end, exclude_template_id=template_id)
            updates['walk_order_start'] = new_start
            updates['walk_order_end'] = new_end
 
        if not updates:
            return False
 
        return self.repo.update(template_id, updates)
    
    # --- DELETE:
 
    def delete_template(self, template_id: int) -> bool:
        """
         Delete a template.

        ⚠️ Not verified safe: work_folders.template_id has an ON DELETE RESTRICT foreign key to folder_templates (see schema.sql). 
        If any work_folder still references this template, this will likely raise a raw database error
        rather than a clean ValueError. Nothing is released or checked here.

        Returns: True if deleted
        Raises: ValueError if template not found
                (may also raise an unhandled DB error if folders still reference it - TODO)
        """
        if not self.repo.exists(template_id):
            raise ValueError(f"תבנית {template_id} לא נמצאה במערכת")

        return self.repo.delete(template_id)
    
    def delete_all_client_templates(self, client_id: int) -> int:
        """
        Delete all templates for a client.
 
        ⚠️ Same RESTRICT risk as delete_template, applied per-template - deletion is not guarded against work_folders that still reference any of them.

        Returns: Number of deleted templates
        Raises: ValueError if client not found
                (may also raise an unhandled DB error if folders still reference some template - TODO)
        """
        self._ensure_client_exists(client_id)
        return self.repo.delete_all_by_client(client_id)