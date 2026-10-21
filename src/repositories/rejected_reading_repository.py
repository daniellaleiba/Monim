"""
Rejected Reading Repository - Data Access Layer

Data access for rejected_readings: readings from the mobile app that the server
could not accept for a permanent reason (e.g. meter_not_found), kept so the manager
can see and handle them. The table holds only open problems: rows are removed once
a reading for that meter in that folder is accepted.
"""

from database.connection import Database
from typing import List, Optional
from psycopg2.extras import Json


class RejectedReadingRepository:
    """
    Data Access Layer for rejected_readings table.

    Responsibilities:
        - save a rejection (one row per reading version; a repeat updates it)
        - list a folder's open rejections (for the manager)
        - get by version id
        - delete a meter's rejections in a folder (once the problem is solved)

    Note: which reasons are saved, and when rows are deleted, is decided by the
          Service (MobileService), not here.

    Relevant indexes:
        - idx_rejected_readings_folder_meter (folder_id, meter_number)
        - UNIQUE (version_id)
    """

    def __init__(self):
        self.db = Database()

    # --- CREATE / UPDATE:

    def save(self, folder_id: int, version_id: str, meter_number: str,
             reason: str, payload: dict) -> dict:
        """
        Save a rejected reading, in one statement:
            - a new version: inserts a row (attempts = 1)
            - a version already saved: attempts + 1, and the latest time, reason and payload replace the old ones (no duplicate row)

        Args:
            folder_id: The folder (package) the reading was sent to
            version_id: The reading version's UUID from the app (UNIQUE)
            meter_number: The meter number as the app sent it
            reason: The rejection code, e.g. 'meter_not_found'
            payload: The reading exactly as the app sent it (stored as JSONB)

        Returns: The saved row
        """
        return self.db.execute_query("""
            INSERT INTO rejected_readings
                (folder_id, version_id, meter_number, reason, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (version_id) DO UPDATE SET
                attempts = rejected_readings.attempts + 1,
                last_rejected_at = CURRENT_TIMESTAMP,
                reason = EXCLUDED.reason,
                payload = EXCLUDED.payload
            RETURNING *
        """, (folder_id, version_id, meter_number, reason, Json(payload)),
            fetch="one", commit=True)

    # --- READ:

    def get_by_version_id(self, version_id: str) -> Optional[dict]:
        """Get the rejection of a reading version, or None if not found."""
        return self.db.execute_query(
            "SELECT * FROM rejected_readings WHERE version_id = %s",
            (version_id,), fetch="one")

    def list_by_folder(self, folder_id: int) -> List[dict]:
        """
        Get a folder's open rejections, most recently rejected first.
        For the manager's screen (planned).
        """
        return self.db.execute_query("""
            SELECT * FROM rejected_readings
            WHERE folder_id = %s
            ORDER BY last_rejected_at DESC
        """, (folder_id,), fetch="all")

    # --- DELETE:

    def delete_by_folder_and_meter(self, folder_id: int, meter_number: str) -> int:
        """
        Delete all rejections of a meter in a folder (every version of it),
        once a reading for that meter was accepted.
        Uses index: idx_rejected_readings_folder_meter

        Returns: Number of rows deleted
        """
        return self.db.execute_query("""
            DELETE FROM rejected_readings
            WHERE folder_id = %s AND meter_number = %s
        """, (folder_id, meter_number), commit=True)