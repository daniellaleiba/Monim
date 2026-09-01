"""
Client Service - Business Logic Layer

Manages clients (water corporations): the top of the data hierarchy that reading periods, folder templates, and (transitively) all their meters and readings belong to. 
Enforces uniqueness on name and corporation number.
"""

from src.repositories.client_repository import ClientRepository
from src.repositories.reading_period_repository import ReadingPeriodRepository
from src.repositories.folder_template_repository import FolderTemplateRepository
from typing import List, Dict, Optional



class ClientService:
    """
    Service for managing clients (water corporations).
 
    Responsibilities:
        - Validate input format and business rules
        - Prevent duplicates (name, corporation number)
        - Manage client creation / update / deletion flow
        - Client is master data - this service does NOT handle
          periods, meters, or folders directly.
    """

    def __init__(self):
        self.repo = ClientRepository()
        self.period_repo = ReadingPeriodRepository() # read only
        self.template_repo = FolderTemplateRepository() # read only

    # --- VALIDATION (Private):
 
    @staticmethod
    def _validate_name(name: str) -> bool:
        """Validate client name: required, at least 2 characters"""
        if not name or not name.strip():
            return False
        length = len(name.strip())
        return 2 <= length <= 100
    
    @staticmethod
    def _validate_corporation_number(corp_num: str) -> bool:
        """
        Validate corporation number:
        - digits only (after removing spaces/dashes)
        - length between 1 and 9 digits
        """
        if not corp_num:
            return False
 
        clean = corp_num.replace(' ', '').replace('-', '')
 
        if not clean.isdigit():  # Must be digits only
            return False
 
        return 1 <= len(clean) <= 9  # Must be 1..9 digits
    
    @staticmethod
    def _normalize_city(city: str) -> Optional[str]:
        """Empty/whitespace-only city normalizes to None, not ''."""
        if not city:
            return None
        city = city.strip()
        return city or None

    # --- CREATE:

    def create_client(self, name: str, corporation_number: str, city: str = None) -> dict:
        """
        Create new client with full validation.

        Validates and normalizes name (min 2 chars, unique) and corporation_number
        (1-9 digits after stripping spaces/dashes, unique) via the _safe_prepare_* helpers. city is stored as-is (stripped), not validated.

        Returns: The created client (full row)
        Raises: ValueError if validation or uniqueness fails
        """
        name = self._safe_prepare_name_(name)
        corporation_number = self._safe_prepare_corporation_number_(corporation_number)
        city = self._normalize_city(city)
        return self.repo.create(name, corporation_number, city)
    
    # --- READ:

    def get_client(self, client_id: int) -> Optional[dict]:
        """Get client by ID, or None if not found"""
        return self.repo.get_by_id(client_id)
    
    def get_client_by_name(self, name: str) -> Optional[dict]:
        """Get client by exact name, or None if not found"""
        return self.repo.get_by_name(name)
    
    def get_client_by_corporation_number(self, corporation_number: str) -> Optional[dict]:
        """Get client by corporation number, or None if not found"""
        return self.repo.get_by_corporation_number(corporation_number)
    
    def list_clients(self) -> List[dict]:
        """Get all clients"""
        return self.repo.list_all()
    
    def search_clients(self, query: str) -> List[dict]:
        """
        Search clients by name or corporation number.
        Empty query returns all clients.
        """
        if not query or not query.strip():
            return self.list_clients()
 
        return self.repo.search(query.strip())
    
    # --- UPDATE:

    def update_client(self, client_id: int, name: str = None,
                      corporation_number: str = None, city: str = None) -> bool:
        """
        Update client details with validation. Only provided fields are updated;
        name and corporation_number go through the same validation/uniqueness checks as create_client.
        Passing an empty string for city clears it to NULL.

        Returns: True if updated, False if nothing to update
        Raises: ValueError if client not found, validation or uniqueness fails
        """
        # Check existence
        if not self.repo.exists(client_id):
            raise ValueError(f"לקוח {client_id} לא נמצא במערכת")
 
        updates = {}

        if name is not None:
            updates['name'] = self._safe_prepare_name_(name, exclude_client_id=client_id)

        if corporation_number is not None:
            updates['corporation_number'] = self._safe_prepare_corporation_number_(
                corporation_number, exclude_client_id=client_id)
        if city is not None:
            updates['city'] = self._normalize_city(city)

        if not updates:
            return False
 
        # All passed - update
        return self.repo.update(client_id, updates)
    
    # --- DELETE:
 
    def delete_client(self, client_id: int) -> bool:
        """
        Delete client.
        Blocked if the client has any reading periods or folder templates; delete those explicitly first if intended. 
        Prevents accidental cascading loss of history via ON DELETE CASCADE.

        Returns: True if deleted
        Raises: ValueError if client not found, or has periods/templates
        """
        if not self.repo.exists(client_id):
            raise ValueError(f"לקוח {client_id} לא נמצא במערכת")

        if self.period_repo.list_by_client(client_id):
            raise ValueError("לא ניתן למחוק תאגיד עם תקופות קריאה קיימות. יש למחוק אותן קודם.")

        if self.template_repo.list_by_client(client_id):
            raise ValueError("לא ניתן למחוק תאגיד עם תבניות תיקים קיימות. יש למחוק אותן קודם.")

        return self.repo.delete(client_id)
    

    # --- UTILITIES (Private helpers):

    def _safe_prepare_name_(self, name: str, exclude_client_id: int = None) -> str:
        """
        Validate format, normalize, and check uniqueness for client name.
        Used by both create and update flows.

        Args:
            name: Raw name input
            exclude_client_id: Client to exclude from uniqueness check (for updates)

        Returns: Cleaned name ready for DB
        Raises: ValueError if invalid or duplicate
        """
        if not self._validate_name(name):
            raise ValueError("שם לא תקין: חייב להיות בין 2 ל-100 תווים")

        name = name.strip()

        if self.repo.name_exists(name, exclude_client_id=exclude_client_id):
            raise ValueError(f"תאגיד בשם '{name}' כבר קיים במערכת")

        return name
    
    def _safe_prepare_corporation_number_(self, corp_num: str, exclude_client_id: int = None) -> str:
        """
        Validate format, normalize, and check uniqueness for corporation number.
        Used by both create and update flows.

        Args:
            corp_num: Raw corporation number input
            exclude_client_id: Client to exclude from uniqueness check (for updates)

        Returns: Cleaned corporation number ready for DB
        Raises: ValueError if invalid or duplicate
        """
        if not self._validate_corporation_number(corp_num):
            raise ValueError("מספר תאגיד לא תקין: חייב להיות רק ספרות באורך עד 9 תווים")

        corp_num = corp_num.replace(' ', '').replace('-', '')

        if self.repo.corporation_number_exists(corp_num, exclude_client_id=exclude_client_id):
            raise ValueError(f"מספר תאגיד '{corp_num}' כבר קיים במערכת")

        return corp_num
