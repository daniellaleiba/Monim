"""  
Period Source File Repository - Data Access Layer


Data access for period_source_files: one row per reading period holding the corporation's uploaded file and its import outcome (processing_status,
rows_count, error_message). UNIQUE(period_id) means uploads overwrite in place rather than keeping history.
"""
 
from database.connection import Database
from typing import Optional

class PeriodSourceFileRepository:
    """
    Data Access Layer for period_source_files table.
 
    Responsibilities:
        - insert / update / select of source file records
        - select by period_id / source_file_id
        - update processing status / rows_count / errors
        - existence checks
        - metadata retrieval
 
    Note: This repository manages the file RECORD, not the file itself.
          File saving to disk is handled by the Service.
          Parsing is handled by external parser helpers.
    """
 
    def __init__(self):
        self.db = Database()

    # --- EXISTENCE CHECKS:
 
    def exists(self, source_file_id: int) -> bool:
        """Check if source file record exists by ID"""
        result = self.db.execute_query(
            "SELECT 1 FROM period_source_files WHERE source_file_id = %s",
            (source_file_id,), fetch="one" )
        return result is not None
 
    def exists_for_period(self, period_id: int) -> bool:
        """
        Check if a source file already exists for this period.
        UNIQUE(period_id) in schema enforces one file per period.
        """
        result = self.db.execute_query(
            "SELECT 1 FROM period_source_files WHERE period_id = %s",
            (period_id,), fetch="one")
        return result is not None
    
    # --- CREATE:
 
    def create(self, period_id: int, original_filename: str, file_type: str, uploaded_by: str = None,
               stored_filename: str = None, file_path: str = None) -> dict:
        """
        Insert new source file record.
 
        Args:
            period_id: Reading period ID (already validated by Service)
            original_filename: Original filename as uploaded
            file_type: File format (e.g. 'excel', 'csv', 'netanya_format')
            uploaded_by: Who uploaded (work manager name/username)
            stored_filename: Filename as saved on disk (may differ from original)
            file_path: Path where file is stored on disk
 
        Returns: The created source file row
        """
        return self.db.execute_query("""
            INSERT INTO period_source_files
                (period_id, original_filename, file_type, uploaded_by,
                 stored_filename, file_path)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (period_id, original_filename, file_type, uploaded_by, stored_filename, file_path),
            fetch="one", commit=True)
    
    # --- READ:
 
    def get_by_id(self, source_file_id: int) -> Optional[dict]:
        """Get source file by ID, or None if not found"""
        return self.db.execute_query("SELECT * FROM period_source_files WHERE source_file_id = %s", (source_file_id,), fetch="one")
 
    def get_by_period(self, period_id: int) -> Optional[dict]:
        """
        Get source file for a specific period, or None if not found.
        Since UNIQUE(period_id), there is at most one file per period.
        """
        return self.db.execute_query("SELECT * FROM period_source_files WHERE period_id = %s",(period_id,), fetch="one")
    
    # --- UPDATE:
 
    def update_processing_status(self, source_file_id: int, status: str) -> bool:
        """
        Update processing status.
        Valid statuses: 'pending', 'success', 'error', 'partial'
        (validation of allowed values is done by Service)
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE period_source_files SET processing_status = %s WHERE source_file_id = %s",
            (status, source_file_id), commit=True)
        
        return rows > 0
 
    def update_rows_count(self, source_file_id: int, rows_count: int) -> bool:
        """
        Update the number of rows found in the file after parsing.
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE period_source_files SET rows_count = %s WHERE source_file_id = %s",
            (rows_count, source_file_id),commit=True)
        
        return rows > 0
 
    def update_error_message(self, source_file_id: int, error_message: str) -> bool:
        """
        Save error message when processing fails.
 
        Returns: True if updated
        """
        rows = self.db.execute_query(
            "UPDATE period_source_files SET error_message = %s WHERE source_file_id = %s",
            (error_message, source_file_id), commit=True)
        
        return rows > 0
    
    def replace_file_metadata(self, source_file_id: int, original_filename: str,
                          stored_filename: str, file_path: str,file_type: str) -> bool:
        """
        Replace file metadata when a new version is uploaded.
        Resets processing status to pending.
        """
        rows = self.db.execute_query("""
            UPDATE period_source_files
            SET original_filename = %s, stored_filename = %s, file_path = %s,
                file_type = %s, processing_status = 'pending',
                error_message = NULL, rows_count = NULL,
                uploaded_at = CURRENT_TIMESTAMP
            WHERE source_file_id = %s
        """, (original_filename, stored_filename, file_path, file_type, source_file_id),
            commit=True)
        return rows > 0
    
    def reset_for_reprocessing(self, source_file_id: int) -> bool:
        """
        Reset processing status to pending for re-processing attempt.
        Clears previous error message and rows count.
        """
        rows = self.db.execute_query("""
            UPDATE period_source_files
            SET processing_status = 'pending', error_message = NULL, rows_count = NULL
            WHERE source_file_id = %s
        """, (source_file_id,), commit=True)
        return rows > 0
    
    # --- DELETE:
 
    def delete(self, source_file_id: int) -> bool:
        """
        Delete source file record.
        Note: period_meters reference this with ON DELETE RESTRICT,
              so deletion will fail if meters were created from this file.
 
        Returns: True if deleted
        """
        rows = self.db.execute_query(
            "DELETE FROM period_source_files WHERE source_file_id = %s",
            (source_file_id,), commit=True)
        return rows > 0