"""  
Work Folder Repository - Data Access Layer


Data access for work_folder: the execution side of work division (created from FolderTemplates per period). 
Handles reader assignment, status lifecycle, cached meter-count tracking, and the enriched query behind the global folders overview screen.
"""
 
from database.connection import Database
from typing import List, Optional
 
 
class WorkFolderRepository:
    """
    Data Access Layer for work_folders table.
 
    WorkFolder is an EXECUTION entity — actual work folders created
    for a specific period, based on FolderTemplates.
 
    Responsibilities:
        - insert / update / select of work folders
        - list by period
        - reader assignment
        - status updates
        - meter count tracking (cached/summary fields)
 
    Note: WorkFolder does NOT contain meters directly.
          Meters reference a folder via period_meters.folder_id.
          ***FolderTemplate is the DEFINITION; WorkFolder is the EXECUTION.***
 
    Relevant indexes:
        - idx_work_folders_period (period_id)
        - idx_work_folders_reader (assigned_to)
    """
 
    def __init__(self):
        self.db = Database()

     # --- EXISTENCE CHECKS:
 
    def exists(self, folder_id: int) -> bool:
        """Check if work folder exists by ID"""
        result = self.db.execute_query(
            "SELECT 1 FROM work_folders WHERE folder_id = %s",
            (folder_id,), fetch="one")
        return result is not None
    
    def exists_for_period_and_template(self, period_id: int, template_id: int) -> bool:
        """
        Check if a work folder already exists for this period + template.
        UNIQUE(period_id, template_id) enforces one folder per template per period.
        """
        result = self.db.execute_query("""
            SELECT 1 FROM work_folders
            WHERE period_id = %s AND template_id = %s
        """, (period_id, template_id), fetch="one")
        return result is not None
    
    # --- CREATE:
 
    def create(self, period_id: int, template_id: int) -> dict:
        """
        Create a new work folder for a period based on a template.
 
        Args:
            period_id: Reading period ID
            template_id: Folder template ID
 
        Returns: The created work folder row
        """
        return self.db.execute_query("""
            INSERT INTO work_folders (period_id, template_id)
            VALUES (%s, %s)
            RETURNING *
        """, (period_id, template_id), fetch="one", commit=True)
    
    # --- READ:
 
    def get_by_id(self, folder_id: int) -> Optional[dict]:
        """Get single work folder by ID, or None if not found"""
        return self.db.execute_query(
            "SELECT * FROM work_folders WHERE folder_id = %s",
            (folder_id,),fetch="one")
 
    def list_by_period(self, period_id: int) -> List[dict]:
        """
        Get all work folders for a period, ordered by creation time.
        Uses index: idx_work_folders_period
        """
        return self.db.execute_query("""
            SELECT * FROM work_folders
            WHERE period_id = %s
            ORDER BY created_at
        """, (period_id,), fetch="all")
 
    def list_by_reader(self, reader_id: int) -> List[dict]:
        """
        Get all work folders assigned to a specific reader.
        Uses index: idx_work_folders_reader
        """
        return self.db.execute_query("""
            SELECT * FROM work_folders
            WHERE assigned_to = %s
            ORDER BY created_at
        """, (reader_id,), fetch="all")
    
    def list_all_with_details(self) -> List[dict]:
        """
        Get all work folders across the entire system, enriched with
        client name, period info, folder name, and reader name.
        Used for the global folders overview screen.

        Sort order: active periods first, then by client name, then newest year/period first, surfaces currently-relevant folders at the top.
        """
        return self.db.execute_query("""
            SELECT wf.folder_id, wf.status AS folder_status, wf.total_meters, wf.completed_meters,
                ft.folder_name, ft.folder_number, c.name AS client_name, rp.period_id, rp.year AS period_year,
                rp.period_number, rp.status AS period_status, r.name  AS reader_name
            FROM work_folders wf JOIN folder_templates ft ON wf.template_id = ft.template_id
                JOIN reading_periods rp  ON wf.period_id   = rp.period_id JOIN clients c ON rp.client_id   = c.client_id
                LEFT JOIN readers r ON wf.assigned_to = r.reader_id
            ORDER BY
                CASE WHEN rp.status = 'active' THEN 0 ELSE 1 END,
                c.name, rp.year DESC, rp.period_number DESC
        """, fetch="all")
    
    # --- UPDATE: Reader assignment
 
    def assign_reader(self, folder_id: int, reader_id: int) -> bool:
        """
        Assign a reader to a work folder.
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE work_folders
            SET assigned_to = %s, assigned_at = CURRENT_TIMESTAMP
            WHERE folder_id = %s
        """, (reader_id, folder_id), commit=True)
        return rows > 0
 
    def clear_reader_assignment(self, folder_id: int) -> bool:
        """
        Remove reader assignment from a folder.
        Sets assigned_to to NULL and clears assigned_at.
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE work_folders
            SET assigned_to = NULL, assigned_at = NULL
            WHERE folder_id = %s
        """, (folder_id,), commit=True)
        return rows > 0
    
    # --- UPDATE: Status:
 
    def update_status(self, folder_id: int, status: str) -> bool:
        """
        Update folder status.
        Valid statuses: 'pending', 'assigned', 'in_progress', 'completed'
        (validation of allowed transitions is done by Service)
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE work_folders SET status = %s WHERE folder_id = %s",
            (status, folder_id), commit=True)
        return rows > 0
 
    def mark_completed(self, folder_id: int) -> bool:
        """
        Mark folder as completed and record completion time.
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE work_folders
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE folder_id = %s
        """, (folder_id,), commit=True)
        return rows > 0
    
    # --- UPDATE: Meter counts (cached/summary)

    def update_counts(self, folder_id: int, total_meters: int, completed_meters: int) -> bool:
        """
        Update cached meter counts for a folder.
        These are summary fields — the real count comes from period_meters table.
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE work_folders
            SET total_meters = %s, completed_meters = %s
            WHERE folder_id = %s
        """, (total_meters, completed_meters, folder_id), commit=True)
        return rows > 0
 
    def increment_completed_meters(self, folder_id: int) -> bool:
        """
        Increment completed_meters by 1.
        Called after a reading is completed for a meter in this folder.
 
        Returns: True if updated
        """
        rows = self.db.execute_query("""
            UPDATE work_folders
            SET completed_meters = completed_meters + 1
            WHERE folder_id = %s
        """, (folder_id,), commit=True)
        return rows > 0
    
    # --- DELETE
 
    def delete(self, folder_id: int) -> bool:
        """
        Delete a work folder.
        Note: period_meters reference this folder — meters with this folder_id
              must be unassigned first (or FK will block deletion).
 
        Returns: True if deleted
        """
        rows = self.db.execute_query(
            "DELETE FROM work_folders WHERE folder_id = %s",
            (folder_id,),
            commit=True
        )
        return rows > 0
 