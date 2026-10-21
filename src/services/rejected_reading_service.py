"""
Rejected Reading Service - Business Logic Layer

Manages readings from the mobile app that the server could not accept for a
permanent reason, so they are never lost and the manager can handle them.
The table holds only open problems: a meter's rejections are removed once a
reading for that meter in that folder is accepted.
"""

from src.repositories.rejected_reading_repository import RejectedReadingRepository
from typing import List, Optional
from src.services import rejection_reasons as reasons


class RejectedReadingService:
    """
    Service for rejected readings from the mobile app.

    Responsibilities:
        - Decide which rejections are saved (permanent reasons only)
        - Save a rejection (a repeat of the same version updates it)
        - Resolve a meter's rejections once a reading for it is accepted
        - Read a folder's open rejections (for the manager's screen, planned)
    """

    def __init__(self):
        self.repo = RejectedReadingRepository()

    # --- SAVE / RESOLVE:

    def record_rejection(self, folder_id: int, item: dict, reason: str) -> Optional[dict]:
        """
        Save a rejected reading if its reason is permanent.

        Args:
            folder_id: The folder (package) the reading was sent to
            item: The reading exactly as the app sent it (one item of the JSON list)
            reason: The rejection code

        Returns: The saved row, or None if not saved (temporary reason,
                 or no version_id to identify the reading by)
        """
        if reason not in reasons.PERMANENT:
            return None

        version_id = item.get('version_id')
        if not version_id:
            return None  # Nothing to identify it by, and nothing the app can resend

        meter_number = str(item.get('meter_number') or '').strip()
        return self.repo.save(folder_id, version_id, meter_number, reason, item)

    def resolve_meter(self, folder_id: int, meter_number: str) -> int:
        """
        A reading for this meter was accepted: its open rejections in this folder
        (every version) are solved, so they are deleted.

        Returns: Number of rejections removed
        """
        return self.repo.delete_by_folder_and_meter(folder_id, str(meter_number).strip())

    # --- READ:

    def get_rejection(self, version_id: str) -> Optional[dict]:
        """The rejection of a reading version, or None."""
        return self.repo.get_by_version_id(version_id)

    def get_folder_rejections(self, folder_id: int) -> List[dict]:
        """A folder's open rejections, most recent first."""
        return self.repo.list_by_folder(folder_id)