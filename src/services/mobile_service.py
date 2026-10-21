"""
Mobile Service - Business Logic Layer

Builds what the reader's mobile app receives, following the WP3 API contract.
Read-only, except for marking downloaded folders through WorkFolderService.
"""

import os
import logging
from datetime import datetime
from typing import List, Optional

from src.services.workfolder_service import WorkFolderService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.reading_period_service import ReadingPeriodService
from src.services.client_service import ClientService
from src.services.fault_code_service import FaultCodeService
from src.services.reading_service import ReadingService
from src.services.photo_service import PhotoService

logger = logging.getLogger(__name__)

# Where photos from the field are saved (one file per reading version)
DEFAULT_PHOTO_DIR = os.path.join('static', 'uploads', 'photos')


class MobileService:
    """
    Service for the mobile app API.

    Responsibilities:
        - Build the download payload: active fault codes + the folders
          released to a reader, each with its meters
        - Mark downloaded folders (through WorkFolderService)
        - Receive readings transmitted from the field: one result per reading
          (accepted / rejected with a reason code), including meters added in the field and photos

    The payload follows the contract: snake_case keys, and every key is
    always present (None when the value is missing).
    """

    def __init__(self, photo_dir: str = DEFAULT_PHOTO_DIR):
        self.folder_service = WorkFolderService()
        self.meter_service = PeriodMeterService()
        self.template_service = FolderTemplateService()
        self.period_service = ReadingPeriodService()
        self.client_service = ClientService()
        self.fault_code_service = FaultCodeService()
        self.reading_service = ReadingService()
        self.photo_service = PhotoService()
        self.photo_dir = photo_dir  # A parameter, so tests can use a temporary folder

    # --- DOWNLOAD:

    def get_download_payload(self, reader_id: int) -> dict:
        """
        Fault codes + all folders released to the reader and not downloaded yet.
        The folders are marked as downloaded only after the whole payload was built,
        so a failure while building marks nothing.

        Returns: dict ready for jsonify
        Raises: ValueError if reader not found
        """
        folders = self.folder_service.get_folders_ready_for_download(reader_id)

        payload = {
            'fault_codes': [
                {'code': fc['code'], 'description': fc['description']}
                for fc in self.fault_code_service.list_active()
            ],
            'packages': [self._build_package(f) for f in folders],
        }

        # Not sent again until the manager re-releases them.
        for folder in folders:
            self.folder_service.mark_folder_downloaded(folder['folder_id'])

        return payload

        # --- TRANSMIT:

    def receive_readings(self, package_id: int, readings: List[dict], photos: dict) -> dict:
        """
        Receive a batch of readings from the app, following the transmit contract.
        Each reading is handled on its own: one bad reading never fails the others.

        Args:
            package_id: The work folder (package) the readings belong to
            readings: The parsed "readings" JSON list from the request
            photos: Uploaded files by part name (photo_<meter_number>); each must
                    have .save(path) and .filename, like Flask's FileStorage

        Returns: {'results': [{'version_id', 'status', 'reason'?}, ...]}
        Raises: ValueError if the package does not exist or has no reader
                (the whole request fails)
        """
        folder = self.folder_service.get_folder(package_id)
        if not folder:
            raise ValueError(f"תיק {package_id} לא נמצא במערכת")
        if not folder.get('assigned_to'):
            raise ValueError(f"תיק {package_id} לא משויך לקורא")

        received_at = datetime.now()
        results = []
        for item in readings:
            version_id = item.get('version_id')
            try:
                reason = self._receive_one(folder, item, photos, received_at)
            except Exception:
                logger.exception(f"Failed to receive reading {version_id} for package {package_id}")
                reason = 'server_error'  # Temporary: the app keeps it and sends it again

            if reason is None:
                results.append({'version_id': version_id, 'status': 'accepted'})
            else:
                results.append({'version_id': version_id, 'status': 'rejected', 'reason': reason})

        return {'results': results}

    # --- TRANSMIT HELPERS (Private):

    def _receive_one(self, folder: dict, item: dict, photos: dict, received_at: datetime) -> Optional[str]:
        """
        Handle one reading. Returns None if accepted, or a rejection reason code.
        All checks run before the first write (see receive_mobile_reading).
        """
        meter_number = str(item.get('meter_number') or '').strip()
        new_meter = item.get('new_meter')
        has_photo = bool(item.get('has_photo'))

        # 1. Checks that need no database write
        try:
            read_at = self._parse_read_at(item.get('read_at'))
            self.reading_service.validate_mobile_reading(
                item.get('version_id'), bool(item.get('is_no_reading')),
                item.get('current_reading'), item.get('fault_code'), item.get('exception_type'))
        except ValueError:
            return 'invalid_data'
        if not meter_number:
            return 'invalid_data'

        photo_file = photos.get(f'photo_{meter_number}') if has_photo else None
        if has_photo and photo_file is None:
            return 'missing_photo'

        # 2. Which meter: in this package, in another folder, or new from the field
        meter = self.meter_service.get_meter_by_number(folder['period_id'], meter_number)
        if meter and meter['folder_id'] != folder['folder_id']:
            return 'meter_exists_in_other_folder' if new_meter else 'meter_not_in_package'
        if not meter:
            if not new_meter:
                return 'meter_not_found'
            try:
                meter = self.meter_service.create_field_meter(
                    folder['period_id'], folder['folder_id'], meter_number,
                    customer_number=new_meter.get('customer_number'),
                    customer_name=new_meter.get('customer_name'),
                    address=new_meter.get('address'),
                    walk_order=new_meter.get('walk_order'))
            except ValueError:
                return 'invalid_data'
            self.folder_service.update_folder_progress(folder['folder_id'])

        # 3. Photo file to disk, before the reading's "done" marker
        photo_path = self._save_photo(photo_file, item['version_id']) if photo_file else None

        # 4. The reading itself (its row is written last)
        result = self.reading_service.receive_mobile_reading(
            meter['period_meter_id'], folder['assigned_to'], item['version_id'],
            is_no_reading=bool(item.get('is_no_reading')),
            current_reading=item.get('current_reading'),
            fault_code=item.get('fault_code'), notes=item.get('notes'),
            exception_type=item.get('exception_type'),
            first_attempt_reading=item.get('first_attempt_reading'),
            photo_missing=bool(item.get('photo_missing')),
            read_at=read_at, received_at=received_at)

        # 5. Photo record, only for a version received now (not a repeat)
        if photo_path and not result['already_received']:
            try:
                self.photo_service.attach_photo_to_reading(result['reading']['reading_id'], photo_path)
            except Exception:
                logger.exception(f"Reading {item['version_id']} saved, but its photo record failed")

        return None

    def _save_photo(self, photo_file, version_id: str) -> str:
        """Save an uploaded photo as <version_id><ext> in the photo folder. Returns its path."""
        os.makedirs(self.photo_dir, exist_ok=True)
        extension = os.path.splitext(getattr(photo_file, 'filename', '') or '')[1] or '.jpg'
        path = os.path.join(self.photo_dir, f"{version_id}{extension}")
        photo_file.save(path)
        return path

    @staticmethod
    def _parse_read_at(value: Optional[str]) -> Optional[datetime]:
        """
        The app sends ISO 8601 in UTC (ending with Z). The DB's TIMESTAMP columns hold
        local time (like CURRENT_TIMESTAMP), so convert to local time without a zone.
        Raises ValueError on a malformed value.
        """
        if not value:
            return None
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is not None:
            moment = moment.astimezone().replace(tzinfo=None)
        return moment
    
    # --- PAYLOAD BUILDERS (Private):

    def _build_package(self, folder: dict) -> dict:
        """One released folder in the contract's package format, with its meters."""
        template = self.template_service.get_template(folder['template_id'])
        period = self.period_service.get_period(folder['period_id'])
        client = self.client_service.get_client(period['client_id'])
        meters = self.meter_service.get_folder_meters(folder['folder_id'])
        include_previous = folder['include_previous_readings']

        return {
            'id': folder['folder_id'],
            'folder_number': template['folder_number'],
            'folder_name': template['folder_name'],
            'client_name': client['name'],
            'period_year': period['year'],
            'period_number': period['period_number'],
            'reader_id': folder['assigned_to'],
            'walk_order_start': template['walk_order_start'],
            'walk_order_end': template['walk_order_end'],
            'include_previous_readings': include_previous,
            'meters': [self._build_meter(m, include_previous) for m in meters],
        }

    @staticmethod
    def _build_meter(meter: dict, include_previous: bool) -> dict:
        """
        One meter in the contract's format.
        previous_reading is None when the folder was released without previous readings.
        """
        previous = meter['previous_reading'] if include_previous else None
        return {
            'meter_number': meter['meter_number'],
            'customer_number': meter['customer_number'],
            'customer_name': meter['customer_name'],
            'address': meter['address'],
            'walk_order': meter['walk_order'],
            'previous_reading': float(previous) if previous is not None else None,
            'manager_notes': meter['manager_notes'],
        }