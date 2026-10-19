"""
Mobile Service - Business Logic Layer

Builds what the reader's mobile app receives, following the WP3 API contract.
Read-only, except for marking downloaded folders through WorkFolderService.
"""

from typing import List

from src.services.workfolder_service import WorkFolderService
from src.services.periodmeter_service import PeriodMeterService
from src.services.folder_template_service import FolderTemplateService
from src.services.reading_period_service import ReadingPeriodService
from src.services.client_service import ClientService
from src.services.fault_code_service import FaultCodeService


class MobileService:
    """
    Service for the mobile app API.

    Responsibilities:
        - Build the download payload: active fault codes + the folders
          released to a reader, each with its meters
        - Mark downloaded folders (through WorkFolderService)
        - (Next step) receive readings transmitted from the field

    The payload follows the contract: snake_case keys, and every key is
    always present (None when the value is missing).
    """

    def __init__(self):
        self.folder_service = WorkFolderService()
        self.meter_service = PeriodMeterService()
        self.template_service = FolderTemplateService()
        self.period_service = ReadingPeriodService()
        self.client_service = ClientService()
        self.fault_code_service = FaultCodeService()

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