"""
Base Parser - Interface for all file format parsers.
Every parser (excel, csv, fixed_width, etc.) must inherit from this
and implement the parse() method.

A parser receives a raw file from a corporation and returns
normalized rows ready for PeriodMeterService.create_meters_from_parsed_rows().

Normalized row format:
{
    'row_number': int,           # Row number in original file (required)
    'meter_number': str,         # Meter number (required)
    'customer_number': str,      # Customer number (optional)
    'customer_name': str,        # Customer name (optional)
    'address': str,              # Address (optional)
    'walk_order': int,           # Walk order for sorting/folder assignment (optional)
    'previous_reading': float,   # Previous reading value (optional)
    'installation_date': str,    # Installation date YYYY-MM-DD (optional)
    'raw_data': dict,            # Original row data as backup (optional)
        -- 'raw_data': {
    'hist_readings': [float],  # [נוכחית, ק1..ק6] - 7 ערכים
    'hist_diffs':    [float],  # [d1..d6] - 6 הפרשים
}
}
"""

from abc import ABC, abstractmethod
from typing import List


class BaseParser(ABC):
    """
    Abstract base class for all file parsers.
    Each corporation format gets its own parser that inherits from this.
    """

    @abstractmethod
    def parse(self, file_path: str) -> List[dict]:
        """
        Parse a raw file and return normalized rows.

        Args:
            file_path: Path to the file on disk

        Returns:
            List of normalized row dicts (see format above)

        Raises:
            ValueError: If file cannot be parsed
            FileNotFoundError: If file doesn't exist
        """
        pass

    @abstractmethod
    def get_file_type(self) -> str:
        """
        Return the file type identifier for this parser.
        Must match the file_type values used in PeriodSourceFile.
        e.g. 'excel', 'csv', 'netanya_format'
        """
        pass

    def validate_row(self, row: dict, row_number: int) -> List[str]:
        """
        Validate a single normalized row. Empty list means row is valid.

        Note: the meter_number check here is defensive; in the actual process_uploaded_file flow, rows without meter_number are already
            filtered out into skipped_rows before validate_all_rows() is called.
        Can be overridden by specific parsers for additional validation.

        Returns: list of error messages
        """
        errors = []

        if not row.get('meter_number'):
            errors.append(f"שורה {row_number}: מספר מונה חסר")

        if row.get('row_number') is None:
            errors.append(f"שורה {row_number}: מספר שורה חסר")

        return errors

    def validate_all_rows(self, rows: List[dict]) -> List[str]:
        """
        Validate all rows and return collected errors.
        """
        all_errors = []
        for row in rows:
            row_num = row.get('row_number', 0)
            errors = self.validate_row(row, row_num)
            all_errors.extend(errors)
        return all_errors