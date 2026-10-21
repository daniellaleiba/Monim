"""  
Reading Repository - Data Access Layer


Data access for readings: the append-only field-event log (every reading attempt, correction, or review action). 
Also has a bulk "latest reading per meter" lookup, used by the meters screen.
"""
 
from database.connection import Database
from typing import List, Optional, Dict
 
 
class ReadingRepository:
    """
    Data Access Layer for readings table.
 
    Reading is a HISTORY/EVENT table - every row is a single reading attempt,
    correction, review, or recheck on a period meter.
 
    Responsibilities:
        - insert of readings
        - select by reading_id / period_meter_id / reader_id / status
        - latest reading lookup
        - status updates
        - history and filtering queries
 
     Note: called by ReadingService.get_latest_readings_for_meters, for the meters screen
            (the reader's notes and transmit time of each meter's latest reading).
            One query for any number of meters, instead of one per meter (N+1).
 
    Relevant indexes:
        - idx_readings_period_meter (period_meter_id)
        - idx_readings_reader (reader_id)
    """
 
    def __init__(self):
        self.db = Database()
    
    # --- EXISTENCE CHECKS:
 
    def exists(self, reading_id: int) -> bool:
        """
        Check if reading exists by ID
        Note: kept for future use, likely relevant once the field-reader mobile app is built (e.g.
            validating a reading still exists before syncing related data like photos).
        """
        result = self.db.execute_query(
            "SELECT 1 FROM readings WHERE reading_id = %s", (reading_id,), fetch="one")
        return result is not None
    
    # --- CREATE:
 
    def create(self, period_meter_id: int, reader_id: int, previous_reading, current_reading, consumption,
        fault_code: str = None, notes: str = None, reading_status: str = 'submitted', transmitted_at=None,
        reading_time=None, is_no_reading: bool = False, first_attempt_reading=None,
        exception_type: str = None, photo_missing: bool = False, version_id: str = None) -> dict:
        """
        Insert a new reading record.

        Args:
            period_meter_id: The meter this reading is for
            reader_id: Who performed the reading
            previous_reading: Snapshot of previous reading at time of read
            current_reading: The actual reading value from the field (None for a no-reading)
            consumption: Calculated consumption (current - previous)
            fault_code: Fault code if applicable
            notes: Reader notes from the field
            reading_status: Initial status (default 'submitted')
            transmitted_at: When the reading reached the server
            reading_time: When the reading was taken in the field; None = now (DB default)
            is_no_reading: The reader could not read the meter
            first_attempt_reading: Value entered before re-verifying an exception
            exception_type: Exception detected by the mobile app, or None
            photo_missing: A photo was taken but its file was lost on the device
            version_id: UUID from the mobile app (UNIQUE); None for other readings

        Returns: The created reading row
        """
        return self.db.execute_query("""
            INSERT INTO readings
                (period_meter_id, reader_id, previous_reading, current_reading,
                 consumption, fault_code, notes, reading_status, transmitted_at,
                 reading_time, is_no_reading, first_attempt_reading,
                 exception_type, photo_missing, version_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s, %s)
            RETURNING *
        """, (period_meter_id, reader_id, previous_reading, current_reading,
              consumption, fault_code, notes, reading_status, transmitted_at,
              reading_time, is_no_reading, first_attempt_reading,
              exception_type, photo_missing, version_id),
            fetch="one", commit=True)
    
    # --- READ: Single record 
 
    def get_by_id(self, reading_id: int) -> Optional[dict]:
        """Get single reading by ID, or None if not found"""
        return self.db.execute_query(
            "SELECT * FROM readings WHERE reading_id = %s",
            (reading_id,), fetch="one")

    def get_by_version_id(self, version_id: str) -> Optional[dict]:
        """
        Get the reading with this mobile version ID, or None if not found.
        Used to detect a reading the server already received (duplicate transmission).
        version_id is UNIQUE, so at most one row matches (its UNIQUE index serves this lookup).
        """
        return self.db.execute_query(
            "SELECT * FROM readings WHERE version_id = %s",
            (version_id,), fetch="one")
 
    def get_latest_by_period_meter(self, period_meter_id: int) -> Optional[dict]:
        """
        Get the most recent reading for a meter.
        Ordered by reading_time DESC, returns the first one.
        """
        return self.db.execute_query("""
            SELECT * FROM readings
            WHERE period_meter_id = %s
            ORDER BY reading_time DESC, reading_id DESC
            LIMIT 1
        """, (period_meter_id,), fetch="one")
    
    def get_latest_by_period_meter_ids(self, period_meter_ids: List[int]) -> Dict[int, dict]:
        """
        Get the latest reading for each meter in a list - one query instead of N.
        Returns a dict: {period_meter_id: reading_row}

        Note: not currently called from any service, written as a ready-made N+1 fix (same ANY(%s) pattern used elsewhere for the meters screen) for
            a future feature that needs "latest reading per meter" across a list (e.g. a bulk readings view). Safe to wire in when that need arises.
        """
        if not period_meter_ids:
            return {}
        
        rows = self.db.execute_query("""
            SELECT DISTINCT ON (period_meter_id) *
            FROM readings
            WHERE period_meter_id = ANY(%s)
            ORDER BY period_meter_id, reading_time DESC, reading_id DESC
        """, (period_meter_ids,), fetch="all")
        
        return {row['period_meter_id']: row for row in rows}

    # --- READ: Lists

    def list_by_period_meter(self, period_meter_id: int) -> List[dict]:
        """
        Get all readings for a specific meter, ordered by time (newest first).
        Uses index: idx_readings_period_meter
        """
        return self.db.execute_query("""
            SELECT * FROM readings
            WHERE period_meter_id = %s
            ORDER BY reading_time DESC
        """, (period_meter_id,), fetch="all")
 
    def list_by_reader(self, reader_id: int) -> List[dict]:
        """
        Get all readings performed by a specific reader.
        Uses index: idx_readings_reader
        """
        return self.db.execute_query("""
            SELECT * FROM readings
            WHERE reader_id = %s
            ORDER BY reading_time DESC
        """, (reader_id,), fetch="all")
 
    def list_by_status(self, reading_status: str) -> List[dict]:
        """Get all readings with a specific status"""
        return self.db.execute_query("""
            SELECT * FROM readings
            WHERE reading_status = %s
            ORDER BY reading_time DESC
        """, (reading_status,), fetch="all")
 
    def list_by_period(self, period_id: int) -> List[dict]:
        """
        Get all readings for a period (across all meters).
        Joins through period_meters to find readings for this period.
        """
        return self.db.execute_query("""
            SELECT r.* FROM readings r
            JOIN period_meters pm ON r.period_meter_id = pm.period_meter_id
            WHERE pm.period_id = %s
            ORDER BY r.reading_time DESC
        """, (period_id,), fetch="all")
    
    # --- UPDATE:
 
    def update_status(self, reading_id: int, reading_status: str) -> bool:
        """
        Update reading status.
        Valid statuses: 'submitted', 'requires_review', 'approved', 'rejected', 'recheck'
        (validation of allowed transitions is done by Service)
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE readings SET reading_status = %s WHERE reading_id = %s",
            (reading_status, reading_id),commit=True)
        return rows > 0
    
    # --- COUNTS:
 
    def count_by_period_meter(self, period_meter_id: int) -> int:
        """Count readings for a specific meter"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM readings WHERE period_meter_id = %s",
            (period_meter_id,),fetch="one")
        return result['count']
 
    def count_by_reader(self, reader_id: int) -> int:
        """Count readings performed by a reader"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM readings WHERE reader_id = %s",
            (reader_id,),fetch="one")
        return result['count']
 
    def count_by_status(self, reading_status: str) -> int:
        """Count readings with a specific status"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM readings WHERE reading_status = %s",
            (reading_status,),fetch="one")
        return result['count']
    
    # --- DELETE:

    def delete(self, reading_id: int) -> bool:
        """
        Delete a reading.
        CASCADE will remove related photos.

        Returns: True if deleted
        """
        rows = self.db.execute_query(
            "DELETE FROM readings WHERE reading_id = %s",
            (reading_id,),commit=True)
        return rows > 0