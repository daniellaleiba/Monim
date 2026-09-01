"""  
Reading Period Repository - Data Access Layer


Data access for reading_periods: the 2-month billing cycle everything else (source files, meters, folders) hangs off of. 
Handles lookup by business identity (client + year + period_number), the previous-period comparison query, and status updates.
"""
 
from database.connection import Database
from typing import List, Optional
 
 
class ReadingPeriodRepository:
    """
    Data Access Layer for reading_periods table.
 
    Responsibilities:
        - insert / update / select of reading periods
        - search by business identifiers (client, year, period_number)
        - list queries by client / year
        - previous period lookup
        - existence checks
        - status updates
 
    Note: ReadingPeriod is a framework entity, it does NOT handle
          file imports, meters, or folder logic. It only manages
          the period record itself.
    """
 
    def __init__(self):
        self.db = Database()

    # --- EXISTENCE CHECKS:
 
    def exists(self, period_id: int) -> bool:
        """
        Check if period exists by ID

        Note: not currently used, relevant for the future field-reader app.
        """
        result = self.db.execute_query(
            "SELECT 1 FROM reading_periods WHERE period_id = %s",
            (period_id,), fetch="one")
        return result is not None
 
    def exists_by_identity(self, client_id: int, year: int, period_number: int) -> bool:
        """
        Check if a period already exists for this client + year + period_number.
        Useful before creating a new period to prevent duplicates.
        """
        result = self.db.execute_query("""
            SELECT 1 FROM reading_periods
            WHERE client_id = %s AND year = %s AND period_number = %s
        """, (client_id, year, period_number), fetch="one")
        return result is not None
    
    # --- CREATE:

    def create(self, client_id: int, year: int, period_number: int,
               start_date, end_date) -> dict:
        """
        Insert new reading period.
 
        Args:
            client_id: Client ID (already validated by Service)
            year: Year (e.g. 2025)
            period_number: Period number 1-6
            start_date: Period start date
            end_date: Period end date
 
        Returns: The created period row
        """
        return self.db.execute_query("""
            INSERT INTO reading_periods (client_id, year, period_number, start_date, end_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (client_id, year, period_number, start_date, end_date),
            fetch="one", commit=True)
    
    # --- READ:
 
    def get_by_id(self, period_id: int) -> Optional[dict]:
        """Get single period by ID, or None if not found"""
        return self.db.execute_query(
            "SELECT * FROM reading_periods WHERE period_id = %s",
            (period_id,), fetch="one")
 
    def get_by_identity(self, client_id: int, year: int, period_number: int) -> Optional[dict]:
        """
        Get period by its business identity (client + year + period_number).
        Returns None if not found.
        """
        return self.db.execute_query("""
            SELECT * FROM reading_periods
            WHERE client_id = %s AND year = %s AND period_number = %s
        """, (client_id, year, period_number), fetch="one")
    
    def list_by_client(self, client_id: int) -> List[dict]:
        """
        Get all periods for a client, ordered by year and period number (newest first).
        Uses index: idx_periods_client
        """
        return self.db.execute_query("""
            SELECT * FROM reading_periods
            WHERE client_id = %s
            ORDER BY year DESC, period_number DESC
        """, (client_id,), fetch="all")
    
    def list_by_client_and_year(self, client_id: int, year: int) -> List[dict]:
        """
        Get all periods for a client in a specific year, ordered by period number.
        Uses index: idx_periods_client

        Sort order: active period first, then by period number descending.
        Surfaces the currently-relevant period at the top of the list.
        """
        return self.db.execute_query("""
            SELECT * FROM reading_periods
            WHERE client_id = %s AND year = %s
            ORDER BY 
                CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                period_number DESC
        """, (client_id, year), fetch="all")
    
    def get_previous_period(self, client_id: int, year: int, period_number: int) -> Optional[dict]:
        """
        Get the period that comes before the given one for the same client.
 
        Logic:
            - If period_number > 1: previous is same year, period_number - 1
            - If period_number == 1: previous is previous year, period 6
 
        Returns: Previous period dict, or None if not found
        """
        if period_number > 1:
            prev_year = year
            prev_number = period_number - 1
        else:
            # Period 1 of current year → Period 6 of previous year
            prev_year = year - 1
            prev_number = 6
 
        return self.db.execute_query("""
            SELECT * FROM reading_periods
            WHERE client_id = %s AND year = %s AND period_number = %s
        """, (client_id, prev_year, prev_number), fetch="one")
    
    # --- UPDATE:
 
    def update_status(self, period_id: int, status: str) -> bool:
        """
        Update period status.
 
        Valid statuses: 'pending', 'file_received', 'active', 'completed', 'skipped'
        (validation of allowed transitions is done in Service)
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE reading_periods SET status = %s WHERE period_id = %s",
            (status, period_id), commit=True)
        return rows > 0
    
    def update_dates(self, period_id: int, start_date, end_date) -> bool:
        """
        Update period start and end dates.

        Note: not yet wired into a service, planned for future manual date editing per period. 
        See ReadingPeriodService._validate_dates().
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE reading_periods SET start_date = %s, end_date = %s WHERE period_id = %s",
            (start_date, end_date, period_id),commit=True)
        return rows > 0
    
    # --- DELETE:
 
    def delete(self, period_id: int) -> bool:
        """
        Delete period.
        CASCADE will remove related source files, meters, folders.
 
        Returns: True if deleted
        """
        rows = self.db.execute_query(
            "DELETE FROM reading_periods WHERE period_id = %s",
            (period_id,), commit=True)
        return rows > 0