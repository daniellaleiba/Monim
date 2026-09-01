"""
Reader Service - Business Logic Layer

Manages readers: the field workers who perform meter readings. 
Enforces username uniqueness, tracks active/inactive status, and handles password updates. 
Reader assignment to work folders and reading history live in their own services (WorkFolderService, ReadingService).
"""

from src.repositories.reader_repository import ReaderRepository
from typing import List, Optional

class ReaderService:
    """
    Service for managing readers (field workers).
 
    Responsibilities:
        - Validate input format and business rules
        - Prevent duplicate usernames
        - Manage reader creation / update flow
        - Manage active/inactive status
        - Reader represents the person - work folder assignments
          and readings belong to their own services.
    """
 
    def __init__(self):
        self.repo = ReaderRepository()
    
    # --- VALIDATION (Private):

    @staticmethod
    def _validate_name(name: str) -> bool:
        """Validate reader name: required, at least 2 characters"""
        if not name or not name.strip():
            return False
        return len(name.strip()) >= 2
    
    @staticmethod
    def _validate_username(username: str) -> bool:
        """
        Validate username:
        - required, 3-50 characters
        - letters (any script - Hebrew included, since Python's str.isalnum()
        is Unicode-aware, not ASCII-only), digits, and underscores only
        """
        if not username or not username.strip():
            return False
        clean = username.strip()
        if len(clean) < 3 or len(clean) > 50:
            return False
        return clean.replace('_', '').isalnum()
    
    @staticmethod
    def _validate_phone(phone: str) -> bool:
        """
        Validate phone number (optional field):
        - digits only (after removing spaces/dashes)
        - 9 to 15 digits
        """
        if not phone:
            return True  # phone is optional - None/empty is valid
        clean = phone.replace(' ', '').replace('-', '')
        if not clean.isdigit():
            return False
        return 9 <= len(clean) <= 15
    
    # --- UTILITIES (Private helpers):

    def _safe_prepare_name(self, name: str) -> str:
        """
        Validate and normalize reader name.
        Returns: Cleaned name ready for DB
        Raises: ValueError if invalid
        """
        if not self._validate_name(name):
            raise ValueError("שם לא תקין: חייב להיות לפחות 2 תווים")
        return name.strip()
    
    def _safe_prepare_username(self, username: str, exclude_reader_id: int = None) -> str:
        """
        Validate format, normalize, and check uniqueness for username.
        Used by both create and update flows.
 
        Args:
            username: Raw username input
            exclude_reader_id: Reader to exclude from uniqueness check (for updates)
 
        Returns: Cleaned username ready for DB
        Raises: ValueError if invalid or duplicate
        """
        if not self._validate_username(username):
            raise ValueError("שם משתמש לא תקין: לפחות 3 תווים, אותיות ספרות וקו תחתון בלבד")
 
        username = username.strip()
 
        if self.repo.username_exists(username, exclude_reader_id=exclude_reader_id):
            raise ValueError(f"שם משתמש '{username}' כבר קיים במערכת")
 
        return username

    def _safe_prepare_phone(self, phone: str) -> Optional[str]:
        """
        Validate and normalize phone number.
        Returns: Cleaned phone or None if empty
        Raises: ValueError if invalid format
        """
        if not phone or not phone.strip():
            return None
        if not self._validate_phone(phone):
            raise ValueError("מספר טלפון לא תקין: חייב להיות ספרות בלבד, 9-15 ספרות")
        return phone.replace(' ', '').replace('-', '')
    
    # --- CREATE:
 
    def create_reader(self, name: str, username: str, password_hash: str, phone: str = None) -> dict:
        """
        Create new reader with full validation.

        Returns: The created reader (full row)
        Raises: ValueError if validation or uniqueness fails

        Note: whether password_hash is excluded from the returned row depends on ReaderRepository.
            create()'s RETURNING clause - worth confirming this doesn't leak the hash anywhere this return value is logged/displayed.
        """
        name = self._safe_prepare_name(name)
        username = self._safe_prepare_username(username)
        phone = self._safe_prepare_phone(phone)
 
        if not password_hash:
            raise ValueError("סיסמה היא שדה חובה")
 
        return self.repo.create(name, username, password_hash, phone)
    
    # --- READ:
 
    def get_reader(self, reader_id: int) -> Optional[dict]:
        """Get reader by ID, or None if not found"""
        return self.repo.get_by_id(reader_id)
 
    def get_reader_by_username(self, username: str) -> Optional[dict]:
        """Get reader by username, or None if not found"""
        return self.repo.get_by_username(username)
 
    def list_readers(self, active_only: bool = False) -> List[dict]:
        """
        Get all readers.
        Args:
            active_only: If True, return only active readers
        """
        return self.repo.list_all(active_only=active_only)
    
    def search_readers(self, query: str) -> List[dict]:
        """
        Search readers by name or username.
        Empty query returns all readers.
        """
        if not query or not query.strip():
            return self.list_readers()
        return self.repo.search(query.strip())
    
    # --- UPDATE:

    def update_reader(self, reader_id: int, name: str = None,
                      username: str = None, phone: str = None) -> bool:
        """
        Update reader details with validation.
 
        Returns: True if updated, False if nothing to update
        Raises: ValueError if reader not found, validation or uniqueness fails
        """
        if not self.repo.exists(reader_id):
            raise ValueError(f"קורא {reader_id} לא נמצא במערכת")
 
        updates = {}
 
        if name is not None:
            updates['name'] = self._safe_prepare_name(name)
 
        if username is not None:
            updates['username'] = self._safe_prepare_username(username, exclude_reader_id=reader_id)
 
        if phone is not None:
            updates['phone'] = self._safe_prepare_phone(phone)
 
        if not updates:
            return False
 
        return self.repo.update(reader_id, updates)
 
    def update_password(self, reader_id: int, new_password_hash: str) -> bool:
        """
        Update reader password.
 
        Returns: True if updated
        Raises: ValueError if reader not found or empty password
        """
        if not self.repo.exists(reader_id):
            raise ValueError(f"קורא {reader_id} לא נמצא במערכת")
 
        if not new_password_hash:
            raise ValueError("סיסמה חדשה היא שדה חובה")
 
        return self.repo.update_password(reader_id, new_password_hash)
    
    # --- ACTIVE / INACTIVE:
 
    def activate_reader(self, reader_id: int) -> bool:
        """
        Activate a reader.

        Returns: True if updated
        Raises: ValueError if reader not found
        """
        if not self.repo.exists(reader_id):
            raise ValueError(f"קורא {reader_id} לא נמצא במערכת")
        return self.repo.set_active_status(reader_id, True)
 
    def deactivate_reader(self, reader_id: int) -> bool:
        """
        Deactivate a reader.

        Returns: True if updated
        Raises: ValueError if reader not found

        TODO: Add a safety check: warn or prevent deactivation if reader has active work folders. 
            WorkFolderRepository is available; this is a conscious choice left unimplemented for now.
        """
        if not self.repo.exists(reader_id):
            raise ValueError(f"קורא {reader_id} לא נמצא במערכת")
        return self.repo.set_active_status(reader_id, False)
    
    # --- DELETE:
 
    def delete_reader(self, reader_id: int) -> bool:
        """
        Delete reader.

        Note: readings.reader_id and work_folders.assigned_to are ON DELETE SET NULL (not CASCADE) - existing readings and folders are kept,
            but lose their reader reference. Historical readings will show no reader after this.

        Returns: True if deleted
        Raises: ValueError if reader not found

        TODO: Add a safety check before deletion if the reader has active work folders or reading history. 
            WorkFolderRepository and ReadingRepository are both available; this is a conscious choice left unimplemented for now.
        """
        if not self.repo.exists(reader_id):
            raise ValueError(f"קורא {reader_id} לא נמצא במערכת")
        return self.repo.delete(reader_id)