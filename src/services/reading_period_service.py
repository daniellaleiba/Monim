"""
Reading Period Service - Business Logic Layer


Manages ReadingPeriod : the 2-month billing cycle that everything else (source files, meters, folders) hangs off of. 
Owns the fixed period calendar, enforces the status lifecycle (pending → file_received → active → completed, or → skipped), and initializes a full year of periods per client.
"""
 
from src.repositories.reading_period_repository import ReadingPeriodRepository
from src.repositories.client_repository import ClientRepository
from typing import List, Optional
import calendar
from datetime import date

# Fixed period calendar: period_number → (start_month, end_month)
PERIOD_CALENDAR = {
    1: (1, 2),    # January - February
    2: (3, 4),    # March - April
    3: (5, 6),    # May - June
    4: (7, 8),    # July - August
    5: (9, 10),   # September - October
    6: (11, 12),  # November - December
}

# Allowed status transitions: current_status → [allowed next statuses]
STATUS_TRANSITIONS = {
    'pending':       ['file_received', 'skipped'],
    'file_received': ['active'],
    'active':        ['completed'],
    'completed':     [],       # final state -- > no transitions allowed
    'skipped':       [],       # final state -- > period was not relevant
}

class ReadingPeriodService:
    """
    Service for managing reading periods.
 
    Responsibilities:
        - Validate period creation
        - Prevent duplicate periods
        - Manage period lifecycle (status transitions)
        - Initialize full year of periods for a client
        - Find previous period for comparison
        - ReadingPeriod is a framework entity - file imports,
          meters, and folders are handled by their own services.
    """
 
    def __init__(self):
        self.repo = ReadingPeriodRepository()
        self.client_repo = ClientRepository()

    # --- VALIDATION (Private):
 
    @staticmethod
    def _validate_year(year: int) -> bool:
        """Validate year: previous year, current year, or next year"""
        current_year = date.today().year
        return isinstance(year, int) and (current_year - 1) <= year <= (current_year + 1)
 
    @staticmethod
    def _validate_period_number(period_number: int) -> bool:
        """Validate period number: must be 1-6"""
        return isinstance(period_number, int) and 1 <= period_number <= 6
 
    @staticmethod
    def _validate_dates(year: int, period_number: int, start_date, end_date) -> bool:
        """
        Validate that dates match the expected period calendar.
        Uses calendar module to handle leap years automatically.

        Note: not yet called anywhere, planned for future manual date editing.
        """
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            return False

        start_month, end_month = PERIOD_CALENDAR[period_number]

        expected_start = date(year, start_month, 1)
        last_day = calendar.monthrange(year, end_month)[1]
        expected_end = date(year, end_month, last_day)

        return start_date == expected_start and end_date == expected_end
 
    def _ensure_client_exists(self, client_id: int):
        """Verify that the client exists. Raises ValueError if not found"""
        if not self.client_repo.exists(client_id):
            raise ValueError(f"תאגיד {client_id} לא נמצא במערכת")
 
    def _ensure_period_exists(self, period_id: int) -> dict:
        """
        Verify period exists and return it.
        Raises ValueError if not found.
        """
        period = self.repo.get_by_id(period_id)
        if not period:
            raise ValueError(f"תקופה {period_id} לא נמצאה במערכת")
        return period
 
    def _validate_status_transition(self, current_status: str, new_status: str):
        """
        Validate that the status transition is allowed.
        Raises ValueError if transition is not allowed.
        """
        allowed = STATUS_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise ValueError(f"לא ניתן לעבור מסטטוס '{current_status}' לסטטוס '{new_status}'. "
                f"מעברים מותרים: {', '.join(allowed) if allowed else 'אין - סטטוס סופי'}")
        
    # --- CREATE:
 
    def create_period(self, client_id: int, year: int, period_number: int) -> dict:
        """
        Create a single reading period with validation.
        Dates are calculated automatically from PERIOD_CALENDAR.

        Returns: The created period (full row)
        Raises: ValueError if validation fails
        """
        self._ensure_client_exists(client_id)

        if not self._validate_year(year):
            raise ValueError("שנה לא תקינה: חייב להיות שנה קודמת, נוכחית, או הבאה")

        if not self._validate_period_number(period_number):
            raise ValueError("מספר תקופה לא תקין: חייב להיות בין 1 ל-6")

        if self.repo.exists_by_identity(client_id, year, period_number):
            raise ValueError( f"תקופה {period_number} בשנת {year} כבר קיימת עבור תאגיד זה")

        # Calculate dates from calendar
        start_month, end_month = PERIOD_CALENDAR[period_number]
        start_date = date(year, start_month, 1)
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = date(year, end_month, last_day)

        return self.repo.create(client_id, year, period_number, start_date, end_date)
    
    def initialize_periods_for_year(self, client_id: int, year: int,
                                    start_from_period: int = 1) -> List[dict]:
        """
        Create all 6 periods for a client in a given year.
        Periods before start_from_period are marked as 'skipped'.

        Args:
            client_id: Client ID
            year: Year to initialize
            start_from_period: First active period (default 1)

        Returns: List of all created periods (including ones marked 'skipped'), skipping any period_number that already exists for this client/year
        """
        self._ensure_client_exists(client_id)

        if not self._validate_year(year):
            raise ValueError("שנה לא תקינה")

        if not self._validate_period_number(start_from_period):
            raise ValueError("מספר תקופה התחלתי לא תקין: חייב להיות בין 1 ל-6")

        created_periods = []

        for period_number in range(1, 7):
            # Skip if already exists
            if self.repo.exists_by_identity(client_id, year, period_number):
                continue

            start_month, end_month = PERIOD_CALENDAR[period_number]
            start_date = date(year, start_month, 1)
            last_day = calendar.monthrange(year, end_month)[1]
            end_date = date(year, end_month, last_day)

            period = self.repo.create(client_id, year, period_number, start_date, end_date)

            # Mark early periods as skipped
            if period_number < start_from_period:
                self.skip_period(period['period_id'])
                period['status'] = 'skipped'

            created_periods.append(period)

        return created_periods
    
    # --- READ:

    def get_period(self, period_id: int) -> Optional[dict]:
        """Get period by ID, or None if not found"""
        return self.repo.get_by_id(period_id)
 
    def get_period_by_identity(self, client_id: int, year: int,
                               period_number: int) -> Optional[dict]:
        """Get period by business identity (client + year + number)"""
        return self.repo.get_by_identity(client_id, year, period_number)
 
    def list_client_periods(self, client_id: int) -> List[dict]:
        """Get all periods for a client (newest first)"""
        self._ensure_client_exists(client_id)
        return self.repo.list_by_client(client_id)
 
    def list_client_year_periods(self, client_id: int, year: int) -> List[dict]:
        """Get all periods for a client in a specific year"""
        self._ensure_client_exists(client_id)
        return self.repo.list_by_client_and_year(client_id, year)
 
    def get_previous_period(self, period_id: int) -> Optional[dict]:
        """
        Find the previous period for comparison.
        e.g. if current is period 3/2025, returns period 2/2025.
             if current is period 1/2025, returns period 6/2024.
 
        Returns: Previous period dict, or None if not found
        Raises: ValueError if current period not found
        """
        period = self._ensure_period_exists(period_id)
        return self.repo.get_previous_period(period['client_id'], period['year'], period['period_number'])
        
    # --- STATUS MANAGEMENT:
 
    def mark_file_received(self, period_id: int) -> bool:
        """
        Mark period as file_received (after source file upload).
        Only allowed from 'pending' status.

        Returns: True if updated
        Raises: ValueError if period not found or transition not allowed
        """
        period = self._ensure_period_exists(period_id)
        self._validate_status_transition(period['status'], 'file_received')
        return self.repo.update_status(period_id, 'file_received')
 
    def activate_period(self, period_id: int) -> bool:
        """
        Activate period (meters loaded, ready for work).
        Only allowed from 'file_received' status.

        Returns: True if updated
        Raises: ValueError if period not found or transition not allowed
        """
        period = self._ensure_period_exists(period_id)
        self._validate_status_transition(period['status'], 'active')
        return self.repo.update_status(period_id, 'active')
 
    def complete_period(self, period_id: int) -> bool:
        """
        Mark period as completed (all work done).
        Only allowed from 'active' status.

        Returns: True if updated
        Raises: ValueError if period not found or transition not allowed
        """
        period = self._ensure_period_exists(period_id)
        self._validate_status_transition(period['status'], 'completed')
        return self.repo.update_status(period_id, 'completed')
 
    def skip_period(self, period_id: int) -> bool:
        """
        Mark period as skipped (not relevant, e.g. client started mid-year).
        Only allowed from 'pending' status.

        Returns: True if updated
        Raises: ValueError if period not found or transition not allowed
        """
        period = self._ensure_period_exists(period_id)
        self._validate_status_transition(period['status'], 'skipped')
        return self.repo.update_status(period_id, 'skipped')
    
    def update_status_manually(self, period_id: int, new_status: str) -> dict:
        """
        Manual status update for managers: bypasses transition validation (STATUS_TRANSITIONS / _validate_status_transition are not checked here,
        unlike mark_file_received/activate_period/complete_period/skip_period).

        Returns: The updated period record
        Raises: ValueError if new_status is not a valid value, or period not found
        """
        valid_statuses = ('pending', 'file_received', 'active', 'completed', 'skipped')
        if new_status not in valid_statuses:
            raise ValueError(f'סטטוס לא חוקי: {new_status}')
        
        period = self.repo.get_by_id(period_id)
        if not period:
            raise ValueError('תקופה לא נמצאה')
        
        self.repo.update_status(period_id, new_status)
        return self.repo.get_by_id(period_id)

    # --- DELETE ---
 
    def delete_period(self, period_id: int) -> bool:
        """
        Delete period.
 
        ⚠️ Cascading delete: removes ALL related data via DB CASCADE -
        period_source_files, period_meters, work_folders (and transitively their
        readings/photos) for this period. Large, irreversible operation.

        Returns: True if deleted
        Raises: ValueError if period not found

        TODO: Add a safety check (e.g. warn/prevent) before deletion if the period
            has meters or active work. PeriodMeterRepository is available; this
            is a conscious choice left unimplemented for now.
        """
        self._ensure_period_exists(period_id)
        return self.repo.delete(period_id)