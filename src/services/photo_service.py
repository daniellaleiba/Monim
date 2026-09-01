"""
Photo Service - Business Logic Layer

Manages photo DB records that document field readings: attaching photos to readings, checking whether exception readings have required photo evidence,
and removing records. Physical file I/O on disk is handled by the caller (route layer), not by this service.
"""
 
from src.repositories.photo_repository import PhotoRepository
from src.repositories.reading_repository import ReadingRepository
from typing import List, Optional
 
 
class PhotoService:
    """
    Service for managing photos - visual documentation for readings.
 
    Photo is a supporting entity. It is always attached to a Reading, never directly to a PeriodMeter.
 
    Responsibilities:
        - Validate photo uploads
        - Manage photo DB records (path + metadata)
        - Attach photos to readings
        - Check business rules (e.g. "exception readings must have a photo")

        Note: Physical file I/O is NOT handled here. The caller must save the file to disk before calling attach_photo_to_reading.
          Physical file deletion on remove_photo/remove_reading_photos is not yet implemented - only DB records are removed (see TODOs below).
        
    """
 
    def __init__(self):
        self.repo = PhotoRepository()
        self.reading_repo = ReadingRepository()

     # --- VALIDATION (Private):
 
    @staticmethod
    def _validate_photo_path(photo_path: str) -> bool:
        """Validate photo path: required, not empty"""
        return bool(photo_path and photo_path.strip())
 
    def _ensure_reading_exists(self, reading_id: int) -> dict:
        """Verify reading exists and return it. Raises ValueError if not found."""
        reading = self.reading_repo.get_by_id(reading_id)
        if not reading:
            raise ValueError(f"קריאה {reading_id} לא נמצאה במערכת")
        return reading
 
    def _ensure_photo_exists(self, photo_id: int) -> dict:
        """Verify photo exists and return it. Raises ValueError if not found."""
        photo = self.repo.get_by_id(photo_id)
        if not photo:
            raise ValueError(f"תמונה {photo_id} לא נמצאה במערכת")
        return photo
    
    # --- ATTACH:
 
    def attach_photo_to_reading(self, reading_id: int, photo_path: str) -> dict:
        """
        Attach a photo to a reading.
 
        Note: The physical file should be saved to disk BEFORE calling this method.
              This method only creates the DB record with the path.
 
        Args:
            reading_id: The reading to attach the photo to
            photo_path: Path where the photo file is stored on disk
 
        Returns: The created photo record
        Raises: ValueError if reading not found or path invalid
        """
        self._ensure_reading_exists(reading_id)
 
        if not self._validate_photo_path(photo_path):
            raise ValueError("נתיב תמונה לא תקין")
 
        return self.repo.create(reading_id, photo_path.strip())
    
    # --- READ:
 
    def get_photo(self, photo_id: int) -> Optional[dict]:
        """Get photo by ID, or None if not found"""
        return self.repo.get_by_id(photo_id)
 
    def get_reading_photos(self, reading_id: int) -> List[dict]:
        """Get all photos for a reading"""
        return self.repo.list_by_reading(reading_id)
 
    def reading_has_photos(self, reading_id: int) -> bool:
        """Check if a reading has any photos attached"""
        return self.repo.count_by_reading(reading_id) > 0
    
    # --- BUSINESS RULES ---
 
    def validate_photo_requirement(self, reading_id: int) -> bool:
        """
        Check if a reading meets photo requirements.
        Called by ReadingService.approve_reading before allowing approval of exception readings.
 
        Business rule: readings with fault_code (exceptions/anomalies)
        should have at least one photo as evidence.

        Not yet wired into the approval flow, intended to be called from ReadingService.approve_reading once the photo upload flow exists
        (planned for the field-reader mobile app).

 
        Returns: True if requirement is met, False if photo is missing
        """
        reading = self._ensure_reading_exists(reading_id)
 
        # If reading has a fault code, it needs a photo
        if reading.get('fault_code'):
            return self.reading_has_photos(reading_id)
 
        # No fault code - photo is optional
        return True
    
    # --- DELETE ---
 
    def remove_photo(self, photo_id: int) -> bool:
        """
        Remove a photo record.
 
        Returns: True if deleted
        Raises: ValueError if photo not found
 
        # TODO: Also delete the physical file from disk.
        """
        self._ensure_photo_exists(photo_id)
        return self.repo.delete(photo_id)
 
    def remove_reading_photos(self, reading_id: int) -> int:
        """
        Remove all photos for a reading.
 
        Returns: Number of deleted photos
 
        # TODO: Also delete the physical files from disk.
        """
        self._ensure_reading_exists(reading_id)
        return self.repo.delete_by_reading(reading_id)
 