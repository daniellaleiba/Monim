"""
Period Source File Service - Business Logic Layer

Owns the corporation source-file record and drives the import pipeline:
upload or replace the file, parse it into period_meters via PeriodMeterService, and track processing status through pending → success/partial/error.
"""
 
from src.repositories.periodsourcefile_repository import PeriodSourceFileRepository
from src.repositories.reading_period_repository import ReadingPeriodRepository
from src.services.reading_period_service import ReadingPeriodService 
from src.parsers import get_parser_for_type
from src.services.periodmeter_service import PeriodMeterService
from typing import Optional
 
 
class PeriodSourceFileService:
    """
    Service for managing period source files (corporation files).
 
    Responsibilities:
        - Validate upload requests
        - Ensure period exists before upload
        - Prevent duplicate uploads (or handle replacement)
        - Save file metadata
        - Manage processing flow (trigger parser, handle success/error)
        - Update period status after upload
        - PeriodSourceFile manages the file RECORD.
          Actual parsing is handled by external parser helpers.
          Actual meter creation is handled by PeriodMeterService.
    """

    def __init__(self):
        self.repo = PeriodSourceFileRepository()
        self.period_repo = ReadingPeriodRepository()
        self.meter_service = PeriodMeterService()
        self.period_service = ReadingPeriodService() 

    # --- VALIDATION (Private):
 
    @staticmethod
    def _validate_filename(filename: str) -> bool:
        """Validate filename: required, not empty"""
        return bool(filename and filename.strip())
 
    @staticmethod
    def _validate_file_type(file_type: str) -> bool:
        """Validate file type: must be a known format"""
        known_types = ('excel', 'csv', 'fixed_width', 'netanya_format', 'netanya_d_format')  # extend per corporation
        return bool(file_type and file_type.strip().lower() in known_types)
 
    def _ensure_period_exists(self, period_id: int) -> dict:
        """
        Verify period exists and return it.
        Raises ValueError if not found.
        """
        period = self.period_repo.get_by_id(period_id)
        if not period:
            raise ValueError(f"תקופה {period_id} לא נמצאה במערכת")
        return period
 
    def _ensure_source_file_exists(self, source_file_id: int) -> dict:
        """
        Verify source file exists and return it.
        Raises ValueError if not found.
        """
        source_file = self.repo.get_by_id(source_file_id)
        if not source_file:
            raise ValueError(f"קובץ מקור {source_file_id} לא נמצא במערכת")
        return source_file
    
    # --- UPLOAD:
 
    def upload_period_file(self, period_id: int, original_filename: str, file_type: str, uploaded_by: str = None,
         stored_filename: str = None, file_path: str = None) -> dict:
        """
        Upload a new source file for a period.
 
        Flow:
            1. Validate inputs
            2. Ensure period exists
            3. Check if file already exists for this period
               - If yes: raise error (use replace_period_file instead)
            4. Save file record
            5. Update period status to 'file_received', but only if period is currently 'pending' (no-op if already past that status)
 
        Note: Actual file saving to disk should happen BEFORE calling this method.
              This method only creates the DB record.
 
        Returns: The created source file record
        Raises: ValueError if validation fails or file already exists
        """
        # Validate
        if not self._validate_filename(original_filename):
            raise ValueError("שם קובץ לא תקין")
 
        if not self._validate_file_type(file_type):
            raise ValueError(f"סוג קובץ '{file_type}' לא נתמך במערכת")
 
        # Ensure period exists
        period = self._ensure_period_exists(period_id)
 
        # Check if file already exists for this period
        if self.repo.exists_for_period(period_id):
            raise ValueError("כבר קיים קובץ לתקופה זו. להחלפת הקובץ השתמש בפונקציית החלפה ")
 
        # Save file record
        source_file = self.repo.create(
            period_id=period_id,
            original_filename=original_filename.strip(),
            file_type=file_type.strip().lower(),
            uploaded_by=uploaded_by, stored_filename=stored_filename, file_path=file_path)
 
        # Update period status to file_received
        if period['status'] == 'pending':
            self.period_service.mark_file_received(period_id)
 
        return source_file
 
    def replace_period_file(self, period_id: int, original_filename: str, file_type: str, uploaded_by: str = None,
            stored_filename: str = None, file_path: str = None) -> dict:
        """
        Replace an existing source file for a period.
        Used when corporation sends an updated file.
 
        Flow:
            1. Validate inputs
            2. Ensure period exists
            3. Ensure file exists for this period
            4. Replace file metadata + reset processing status
 
        Note: Existing period_meters from the old file are NOT deleted here,
            the caller is responsible for deleting them first via PeriodMeterService.delete_meters_by_source_file
            (see routes/periods.py upload_file for the expected call order).
 
        Returns: Updated source file record
        Raises: ValueError if validation fails or no file exists to replace
        """
        # Validate
        if not self._validate_filename(original_filename):
            raise ValueError("שם קובץ לא תקין")
 
        if not self._validate_file_type(file_type):
            raise ValueError(f"סוג קובץ '{file_type}' לא נתמך במערכת")
 
        # Ensure period and file exist
        self._ensure_period_exists(period_id)
        existing_file = self.repo.get_by_period(period_id)
 
        if not existing_file:
            raise ValueError("אין קובץ קיים לתקופה זו. השתמש בהעלאה רגילה")
 
        # Replace file metadata and reset processing status('pending')
        self.repo.replace_file_metadata(
            source_file_id=existing_file['source_file_id'],
            original_filename=original_filename.strip(),
            stored_filename=stored_filename,
            file_path=file_path,
            file_type=file_type.strip().lower()
        )
 
        # Return updated record
        return self.repo.get_by_id(existing_file['source_file_id'])
    
    # --- READ:
 
    def get_source_file(self, source_file_id: int) -> Optional[dict]:
        """Get source file by ID, or None if not found"""
        return self.repo.get_by_id(source_file_id)
 
    def get_period_source_file(self, period_id: int) -> Optional[dict]:
        """Get source file for a specific period, or None if not found"""
        return self.repo.get_by_period(period_id)
    
    # --- PROCESSING:
 
    def process_uploaded_file(self, source_file_id: int) -> dict:
        """
        Process an uploaded source file: parse, classify, validate, and create period_meters.
 
        Flow:
            1. Ensure file exists and is in 'pending' status
            2. Get the parser for this file's file_type
            3. Parse the file into normalized rows
            4. Classify rows:
                - No meter_number → skipped (not imported)
                - Missing other optional fields (customer_number, address, walk_order, previous_reading) → imported but flagged
                    work_status='missing_info', with raw_data.missing_fields
                    listing what's absent

            5. Run parser-level validation on importable rows
            6. Create period_meters via PeriodMeterService.create_meters_from_parsed_rows
            7. Determine processing_status: 'partial' if 5%+ of rows were skipped, else 'success'. Builds a Hebrew summary message for skipped/missing-info rows.
            8. Update period status directly to 'active'


        Note: On any exception, the file is marked 'error' (via mark_processing_error) before the exception is re-raised.

        Returns: Updated source file record with processing results
        Raises: ValueError if file not found or not in pending status
        """
        source_file = self._ensure_source_file_exists(source_file_id)
 
        if source_file['processing_status'] != 'pending':
            raise ValueError(
                f"קובץ בסטטוס '{source_file['processing_status']}' - "
                f"ניתן לעבד רק קובץ בסטטוס 'pending'" )
 
        try:
            # 1. Get parser for this file type
            parser = get_parser_for_type(source_file['file_type'])

            # 2. Parse file
            all_rows = parser.parse(source_file['file_path'])
        
            # 3. Classify rows
            importable_rows = []   # יש meter_number → ייבוא
            skipped_rows = []      # אין meter_number → דילוג

            for row in all_rows:
                # No meter_number → skip
                if not row.get('meter_number') or not str(row['meter_number']).strip():
                    skipped_rows.append(row)
                    continue
                
                # Check for missing optional fields
                missing = []
                if not row.get('customer_number'):
                    missing.append('customer_number')
                if not row.get('address'):
                    missing.append('address')
                if not row.get('walk_order') and row.get('walk_order') != 0:
                    missing.append('walk_order')
                if row.get('previous_reading') is None:
                    missing.append('previous_reading')

                if missing:
                    if row.get('raw_data') is None:
                        row['raw_data'] = {}
                    row['raw_data']['missing_fields'] = missing
                    row['work_status'] = 'missing_info'

                importable_rows.append(row)

            if not importable_rows:
                raise ValueError("אין שורות תקינות לייבוא")
            
            # 4. Parser-specific validation (only on importable rows)
            errors = parser.validate_all_rows(importable_rows)
            if errors:
                raise ValueError( f"נמצאו {len(errors)} שגיאות בקובץ:\n" +
                    "\n".join(errors[:20]))

            # 5. Create period meters (work_status already set in each row)
            self.meter_service.create_meters_from_parsed_rows(period_id=source_file['period_id'], source_file_id=source_file_id, parsed_rows=importable_rows)
            
            # 6. Build status message
            messages = []

            if skipped_rows:
                skip_details = []
                for row in skipped_rows[:50]:
                    row_num = row.get('row_number', '?')
                    skip_details.append(f"שורה {row_num}: מספר מונה חסר")

                messages.append( f"{len(skipped_rows)} שורות נדלגו (מספר מונה חסר):\n" +
                    "\n".join(skip_details))

            missing_info_rows = [r for r in importable_rows 
                                 if r.get('raw_data') and r['raw_data'].get('missing_fields')]
            if missing_info_rows:
                missing_details = []
                for row in missing_info_rows[:50]:
                    row_num = row.get('row_number', '?')
                    fields = ', '.join(row['raw_data']['missing_fields'])
                    missing_details.append(f"שורה {row_num}: חסר {fields}")

                messages.append( f"{len(missing_info_rows)} מונים יובאו עם נתונים חסרים:\n" +
                    "\n".join(missing_details))

            # Build full message
            full_msg = None
            if messages:
                full_msg = (f"יובאו {len(importable_rows)} מתוך {len(all_rows)} שורות.\n" +
                    "\n".join(messages))

            # Determine processing status
            skip_ratio = len(skipped_rows) / len(all_rows) if all_rows else 0
            if skip_ratio >= 0.05:
                self.repo.update_processing_status(source_file_id, 'partial')
                self.repo.update_error_message(source_file_id, full_msg)
                self.repo.update_rows_count(source_file_id, len(importable_rows))
            else:
                self.mark_processing_success(source_file_id, len(importable_rows))
                if full_msg:
                    self.repo.update_error_message(source_file_id, full_msg)

            # 7. Update period status only if currently 'file_received', to avoid misreporting a successful import as 'error' if the
            # period is (unexpectedly) already past that status.
            period = self.period_repo.get_by_id(source_file['period_id'])
            if period and period['status'] == 'file_received':
                self.period_service.activate_period(source_file['period_id'])

        except Exception as e:
            self.mark_processing_error(source_file_id, str(e))
            raise
 
        return self.repo.get_by_id(source_file_id)
    
    def retry_processing(self, source_file_id: int) -> dict:
        """
        Retry processing a file that previously failed.
 
        Flow:
            1. Ensure file exists and is in 'error' status
            2. Reset processing status to 'pending'
            3. Delete any partial period_meters from the previous failed attempt
            4. Run process_uploaded_file again
 
        Returns: Updated source file record
        Raises: ValueError if file not found or not in error status
        """
        source_file = self._ensure_source_file_exists(source_file_id)
 
        if source_file['processing_status'] != 'error':
            raise ValueError(
                f"ניסיון חוזר אפשרי רק לקבצים בסטטוס 'error'. "
                f"סטטוס נוכחי: '{source_file['processing_status']}'")
 
        # Reset for reprocessing
        self.repo.reset_for_reprocessing(source_file_id)
 
        # Clean up partial period_meters from failed attempt
        self.meter_service.delete_meters_by_source_file(source_file_id)
 
        # Run processing again
        return self.process_uploaded_file(source_file_id)
    
     # --- PROCESSING STATUS HELPERS:
 
    def mark_processing_success(self, source_file_id: int, rows_count: int) -> bool:
        """
        Mark file as successfully processed.
        Called after parser + meter creation succeed.
        """
        self._ensure_source_file_exists(source_file_id)
        self.repo.update_processing_status(source_file_id, 'success')
        self.repo.update_rows_count(source_file_id, rows_count)
        return True
 
    def mark_processing_error(self, source_file_id: int, error_message: str) -> bool:
        """
        Mark file as failed processing.
        Called when parser or meter creation fails.
        """
        self._ensure_source_file_exists(source_file_id)
        self.repo.update_processing_status(source_file_id, 'error')
        self.repo.update_error_message(source_file_id, error_message)
        return True
    
    # --- DELETE: 
 
    def delete_source_file(self, source_file_id: int) -> bool:
        """
        Delete source file record.
        Will fail if period_meters exist (ON DELETE RESTRICT).
 
        Returns: True if deleted
        Raises: ValueError if file not found
 
        # TODO: Consider also deleting the physical file from disk.
        """
        self._ensure_source_file_exists(source_file_id)
        return self.repo.delete(source_file_id)