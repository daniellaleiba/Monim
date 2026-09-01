"""
Netanya Water Corporation Parser
Parses the Excel file format used by מי נתניה.

Expected columns:
    מס'ד | מס' זיהוי | מספר מונה | מספר משדר | נוכחית | כתובת |
    סדר הליכה | מודל | קוטר | תאריך התקנה | קו אורך | קו רוחב

Notes:
    - מספר משדר is always identical to מספר מונה (ignored)
    - קוטר, קו אורך, קו רוחב are not needed for our system
    - מודל is kept in raw_data for reference
    - נוכחית = the last known reading from the corporation → becomes previous_reading
    - meter_number can be string or int in the file → always converted to string
    - row_number = logical row identifier from source file (usually מס"ד), used for debugging/import traceability
"""

import openpyxl
from datetime import datetime
from typing import List

from .base_parser import BaseParser


# Expected column headers (stripped of whitespace)
EXPECTED_HEADERS = [
    "מס'ד",
    "מס' זיהוי",
    "מספר מונה",
    "מספר משדר",
    "נוכחית",
    "כתובת",
    "סדר הליכה",
    "מודל",
    "קוטר",
    "תאריך התקנה",
    "קו אורך",
    "קו רוחב",
]


class NetanyaParser(BaseParser):
    """
    Parser for Netanya water corporation Excel files.
    """

    def get_file_type(self) -> str:
        return "netanya_format"

    def parse(self, file_path: str) -> List[dict]:
        """
        Parse Netanya Excel file and return normalized rows.

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid (wrong headers, no data)
        """
        wb = openpyxl.load_workbook(file_path, read_only=True)
        ws = wb.active

        rows_iter = ws.iter_rows(values_only=True)

        # --- Read and validate header ---
        try:
            raw_header = next(rows_iter)
        except StopIteration:
            wb.close()
            raise ValueError("הקובץ ריק - אין שורת כותרת")

        header = [str(h).strip() if h is not None else "" for h in raw_header]
        self._validate_headers(header)

        # --- Parse data rows ---
        normalized_rows = []
        for raw_row in rows_iter:
            row = self._parse_row(raw_row)
            if row is not None:
                normalized_rows.append(row)

        wb.close()

        if len(normalized_rows) == 0:
            raise ValueError("הקובץ לא מכיל שורות נתונים")

        return normalized_rows

    def _validate_headers(self, header: List[str]) -> None:
        """
        Validate that the file has the expected column headers.
        Compares stripped versions to handle trailing spaces.

        doubled apostrophes ('' → '): a known artifact from how some Excel exports encode the Hebrew ' character in headers like מס'ד.
        """
        if len(header) < len(EXPECTED_HEADERS):
            raise ValueError( f"מספר עמודות לא תואם: צפוי {len(EXPECTED_HEADERS)}, קיבל {len(header)}")

        for i, expected in enumerate(EXPECTED_HEADERS):
            actual = header[i].strip().replace("''", "'")
            if actual != expected:
                raise ValueError( f"כותרת עמודה {i + 1} לא תואמת: צפוי '{expected}', קיבל '{actual}'" )

    def _parse_row(self, raw_row: tuple) -> dict | None:
        """
        Parse a single raw Excel row into a normalized dict.
        Returns None if row should be skipped (empty row).
        """
        # Skip completely empty rows
        if all(v is None for v in raw_row):
            return None

        row_number = raw_row[0]
        if row_number is None:
            return None

        # meter_number: can be int or str in file, always store as str
        meter_number = raw_row[2]
        if meter_number is not None:
            meter_number = str(meter_number).strip()
        else:
            meter_number = None

        # customer_number: int in file, store as str
        customer_number = raw_row[1]
        if customer_number is not None:
            customer_number = str(customer_number).strip()
            if customer_number == "":
                customer_number = None

        # walk_order: can be None (about 4% of rows)
        walk_order = raw_row[6]
        if walk_order is not None:
            try:
                walk_order = int(walk_order)
            except (ValueError, TypeError):
                walk_order = None

        # previous_reading (נוכחית) - may contain #N/A or other non-numeric values
        previous_reading = raw_row[4]
        if previous_reading is not None:
            try:
                previous_reading = float(previous_reading)
            except (ValueError, TypeError):
                previous_reading = None

        # installation_date: datetime → string YYYY-MM-DD
        installation_date = raw_row[9]
        if isinstance(installation_date, datetime):
            installation_date = installation_date.strftime("%Y-%m-%d")
        elif installation_date is not None:
            installation_date = str(installation_date)

        # raw_data: keep model for reference
        raw_data = { "model": raw_row[7], }
        
        # address: keep inner spaces, clean only edges
        address = str(raw_row[5]).strip() if raw_row[5] is not None else None
        address = address or None

        return {
            "row_number": int(row_number), "meter_number": meter_number, "customer_number": customer_number,
            "customer_name": None, "address": address, "walk_order": walk_order,
            "previous_reading": previous_reading, "installation_date": installation_date, "raw_data": raw_data,
        }

    def validate_row(self, row: dict, row_number: int) -> List[str]:
        """
        Extended validation for Netanya format.

        Note: overlaps with BaseParser's meter_number check (both fire on empty string): kept separate intentionally, in case missing vs. empty need distinct handling later (e.g. for the mobile app).
        """
        errors = super().validate_row(row, row_number)

        # Netanya-specific: meter_number should not be empty string
        if row.get("meter_number") == "":
            errors.append(f"שורה {row_number}: מספר מונה ריק")

        # previous_reading should be non-negative if present
        pr = row.get("previous_reading")
        if pr is not None and pr < 0:
            errors.append(f"שורה {row_number}: קריאה קודמת שלילית ({pr})")

        return errors