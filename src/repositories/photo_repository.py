""" 
Photo Repository - Data Access Layer
"""
 
from database.connection import Database
from typing import List, Optional
 
 
class PhotoRepository:
    """
    Data Access Layer for photos table.
 
    Photo is a SUPPORTING entity, visual documentation attached to readings.
 
    Responsibilities:
        - insert / select / delete of photo records
        - list by reading_id
        - existence checks
 
    Note: This repository manages photo RECORDS (path + metadata), 
          not the physical files. File storage is handled by the Service.
 
    Relevant indexes:
        - idx_photos_reading (reading_id)
    """
 
    def __init__(self):
        self.db = Database()

    # --- EXISTENCE CHECKS:
 
    def exists(self, photo_id: int) -> bool:
        """Check if photo exists by ID"""
        result = self.db.execute_query(
            "SELECT 1 FROM photos WHERE photo_id = %s",
            (photo_id,), fetch="one")
        return result is not None
    
    # --- CREATE:
 
    def create(self, reading_id: int, photo_path: str) -> dict:
        """
        Insert a new photo record.
 
        Args:
            reading_id: The reading this photo belongs to
            photo_path: Path where the photo file is stored on disk
 
        Returns: The created photo row
        """
        return self.db.execute_query("""
            INSERT INTO photos (reading_id, photo_path)
            VALUES (%s, %s)
            RETURNING *
        """, (reading_id, photo_path), fetch="one", commit=True)
    
    # --- READ:
 
    def get_by_id(self, photo_id: int) -> Optional[dict]:
        """Get single photo by ID, or None if not found"""
        return self.db.execute_query(
            "SELECT * FROM photos WHERE photo_id = %s",
            (photo_id,),fetch="one")
 
    def list_by_reading(self, reading_id: int) -> List[dict]:
        """
        Get all photos for a reading, ordered by upload time.
        Uses index: idx_photos_reading
        """
        return self.db.execute_query("""
            SELECT * FROM photos
            WHERE reading_id = %s
            ORDER BY uploaded_at
        """, (reading_id,), fetch="all")
 
    def count_by_reading(self, reading_id: int) -> int:
        """Count photos for a reading"""
        result = self.db.execute_query(
            "SELECT COUNT(*) as count FROM photos WHERE reading_id = %s",
            (reading_id,), fetch="one")
        return result['count']
    

    # --- DELETE:
 
    def delete(self, photo_id: int) -> bool:
        """
        Delete a photo record.
        Note: Does NOT delete the physical file, not implemented anywhere yet (see PhotoService TODOs).
 
        Returns: True if deleted
        """
        rows = self.db.execute_query(
            "DELETE FROM photos WHERE photo_id = %s",
            (photo_id,), commit=True)
        return rows > 0
 
    def delete_by_reading(self, reading_id: int) -> int:
        """
        Delete all photos for a reading.

        Note: mostly redundant with photos.reading_id ON DELETE CASCADE; deleting the reading itself removes its photos automatically. 
        This method is only needed when clearing photos WITHOUT deleting the reading (e.g. re-upload).
 
        Returns: Number of deleted photos
        """
        return self.db.execute_query(
            "DELETE FROM photos WHERE reading_id = %s",
            (reading_id,), commit=True)
 