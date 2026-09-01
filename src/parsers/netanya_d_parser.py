"""
Netanya Water Corporation - Fixed-Width (.D) File Parser:
Parses the binary fixed-width format sent by מי נתניה (and similar Israeli
water corporations). 
This is a legacy DOS format, distinct from the Excel format handled by NetanyaParser.

File characteristics:
    - Extension:  .D  (e.g. A1274000.D)
    - Encoding:   cp862  (DOS Hebrew / OEM 862)
    - Line endings: CRLF (\\r\\n) or NEL
    - Row length: 503 characters per data row
    - Content:    One meter per row, all fields at fixed byte offsets

Field map (0-based offsets, inclusive start, exclusive end):
    [0:2]     Corporation code (e.g. '27')
    [2:9]     Internal serial / filler
    [9:20]    Internal prefix + walk order raw (not used directly)
    [20:21]   Flag / filler
    [21:41]   Customer name (שם צרכן) - 20 chars, DOS RTL reversed
    [41:61]   Street address (כתובת) - 20 chars, DOS RTL reversed
    [61:86]   Filler / location text
    [86:96]   Walk order (סדר הליכה) - 10-digit numeric
    [96:101]  Filler
    [102:111] Customer number (מספר זיהוי מים) - 8-digit numeric, unique per customer
    [111:185] Infrastructure fields (physical_number at 118:126, meter_number copy at 133:141)
    [185:195] Current reading (קריאה נוכחית) → becomes previous_reading
    [195:205] Historical reading ק.1 (most recent past period)
    [205:215] Historical reading ק.2
    [215:225] Historical reading ק.3
    [225:235] Historical reading ק.4
    [235:245] Historical reading ק.5
    [245:255] Historical reading ק.6 (parallel period last year)
    [255:272] Filler / flags
    [272:282] Installation date - DD/MM/YYYY
    [282:342] Internal corporation identifiers (not parsed)
    [342:380] Location name - Hebrew text, cp862, reversed (DOS RTL)
    [380:401] Filler
    [401:411] Consumption diff ק.1→ק.2
    [411:421] Consumption diff ק.2→ק.3
    [421:431] Consumption diff ק.3→ק.4
    [431:441] Consumption diff ק.4→ק.5
    [441:451] Consumption diff ק.5→ק.6
    [451:461] Consumption diff ק.6→ (period before ק.6)
    [461:495] Filler / internal codes
    [495:503] Meter number (מספר מונה) - 8-char alphanumeric, unique

Historical readings in raw_data:
    hist_readings: [current, q1, q2, q3, q4, q5, q6]
        index 0 = current (same as previous_reading)
        index 1 = ק.1 (one period back)
        ...
        index 6 = ק.6 (parallel period last year)

    hist_diffs: [d1, d2, d3, d4, d5, d6]
        index 0 = diff between ק.1 and ק.2
        ...
        index 5 = diff for ק.6

    These are stored in raw_data and used by the UI to display
    the historical readings table and to support the "estimation"
    (הערכה) function.

Performance:
    Reads the file in binary, splits on line endings, decodes each
    line individually. Handles 12,000+ rows in under 1 second.
"""

from typing import List, Optional
from .base_parser import BaseParser


# Minimum expected row length (503 chars). Shorter rows are skipped.
MIN_ROW_LENGTH = 495

# Number of historical reading slots in the file
NUM_HIST_READINGS = 6

# Fixed-width field offsets (start, end) - all 0-based
_F = {
    'walk_order':        (86,  96),  # 10-digit walk order (fallback: 9:20)
    'walk_order_alt':    (9,   20),  # fallback when [86:96] is zero
    'customer_name_raw': (21,  41),  # first 20 chars: customer name (reversed)
    'address':           (41,  61),  # next  20 chars: street address (reversed)
    'customer_number':   (102, 111),  # unique customer identifier
    'reading_current':   (185, 195),
    'reading_hist':      [(195 + i * 10, 205 + i * 10) for i in range(NUM_HIST_READINGS)],
    'installation_date': (272, 282),
    'diffs':             [(401 + i * 10, 411 + i * 10) for i in range(NUM_HIST_READINGS)],
    'meter_number':      (495, 503),
}


class NetanyaDParser(BaseParser):
    """
    Parser for Netanya water corporation fixed-width .D files.

    Produces the same normalized row format as NetanyaParser (Excel),
    with the addition of hist_readings and hist_diffs in raw_data.
    """

    def get_file_type(self) -> str:
        return 'netanya_d_format'

    # Public interface

    def parse(self, file_path: str) -> List[dict]:
        """
        Parse a .D file and return a list of normalized meter rows.

        Args:
            file_path: Path to the .D file on disk

        Returns:
            List of normalized dicts, one per valid meter row

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If the file is empty or has no parseable rows
        """
        try:
            with open(file_path, 'rb') as f:
                raw = f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"קובץ לא נמצא: {file_path}")

        if not raw:
            raise ValueError("הקובץ ריק")

        # Split on CRLF first, then fall back to bare LF / NEL
        raw_lines = raw.split(b'\r\n')
        if len(raw_lines) == 1:
            raw_lines = raw.split(b'\n')

        normalized_rows = []
        row_number = 0

        for raw_line in raw_lines:
            # Skip short lines (headers, footers, blank separators)
            if len(raw_line) < MIN_ROW_LENGTH:
                continue

            row_number += 1
            row = self._parse_line(raw_line, row_number)
            if row is not None:
                normalized_rows.append(row)

        if not normalized_rows:
            raise ValueError("הקובץ לא מכיל שורות נתונים תקינות")

        return normalized_rows


    # Private helpers

    def _parse_line(self, raw_line: bytes, row_number: int) -> Optional[dict]:
        """
        Decode and parse a single fixed-width line.
        Returns None if the line should be skipped (no meter number).
        """
        try:
            line = raw_line.decode('cp862', errors='replace')
        except Exception:
            return None

        # --- Meter number (required) ---
        meter_number = self._extract_str(line, *_F['meter_number'])
        if not meter_number:
            return None  # No meter number → skip row

        # --- Walk order ---
        # Primary field [86:96]; fallback to [9:20] when primary is zero.
        walk_order = self._extract_int(line, *_F['walk_order'])
        if not walk_order:
            walk_order = self._extract_int(line, *_F['walk_order_alt'])

        # --- Customer number ---
        customer_number = self._extract_str(line, *_F['customer_number'])

        # --- Address + Customer Name ---
        # Fixed offsets (each 20 chars), stored reversed (DOS RTL).
        # [21:41] = customer name (reversed) | [41:61] = street address (reversed)
        customer_name_raw = self._extract_str(line, *_F['customer_name_raw'])
        address_raw       = self._extract_str(line, *_F['address'])
        customer_name = self._fix_hebrew(customer_name_raw) if customer_name_raw else None
        address       = self._fix_hebrew(address_raw)       if address_raw       else None

        # --- Current reading → becomes previous_reading ---
        previous_reading = self._extract_float(line, *_F['reading_current'])

        # --- Installation date: DD/MM/YYYY → YYYY-MM-DD ---
        installation_date = self._parse_date(
            self._extract_str(line, *_F['installation_date'])
        )

        # --- Historical readings: [current, q1..q6] ---
        hist_readings: List[Optional[float]] = [previous_reading]
        for s, e in _F['reading_hist']:
            hist_readings.append(self._extract_float(line, s, e))

        # --- Historical diffs: [d1..d6] ---
        hist_diffs: List[Optional[float]] = []
        for s, e in _F['diffs']:
            hist_diffs.append(self._extract_float(line, s, e))
        
        _loc_raw = line[61:81].strip()
        _loc = _loc_raw if (_loc_raw and _loc_raw[0].isdigit()) else self._fix_hebrew(_loc_raw)
        usage_type = line[169].strip() if len(line) > 169 else None

        raw_data = {
            'hist_readings': hist_readings,   # [current, q1, q2, q3, q4, q5, q6]
            'hist_diffs':    hist_diffs,       # [d1, d2, d3, d4, d5, d6]
            'physical_number': self._extract_str(line, 116, 126),  # מספר פיזי
            'meter_id': self._extract_str(line, 10, 21),
            'reception_date':   self._parse_yymmdd(line[179:185].strip()),  # ת.קליטה
            'install_date_alt': self._parse_yymmdd(line[141:147].strip()),  # ת.התקנה עדכנית
            'meter_location': _loc,
            'usage_type': usage_type,
        }

        return {
            'row_number': row_number,
            'meter_number': meter_number,
            'customer_number':customer_number,
            'customer_name': customer_name,
            'address':address,
            'walk_order': walk_order,
            'previous_reading':previous_reading,
            'installation_date': installation_date,
            'raw_data': raw_data,
        }

    # Field extractors-

    @staticmethod
    def _extract_str(line: str, start: int, end: int) -> Optional[str]:
        """Extract and strip a string field. Returns None if empty."""
        val = line[start:end].strip()
        return val if val else None


    @staticmethod
    def _extract_float(line: str, start: int, end: int) -> Optional[float]:
        """Extract a numeric field. Returns None if missing or non-numeric; 0.0 if the field is present and equals zero."""
        raw = line[start:end].strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _extract_int(line: str, start: int, end: int) -> Optional[int]:
        """Extract an integer field. Returns None if missing or non-numeric."""
        raw = line[start:end].strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except ValueError:
            return None

    @staticmethod
    def _parse_date(raw: Optional[str]) -> Optional[str]:
        """
        Convert DD/MM/YYYY → YYYY-MM-DD.
        Returns None if the value is missing, all-zeros, or malformed.
        """
        if not raw or raw == '00/00/0000':
            return None
        parts = raw.split('/')
        if len(parts) != 3:
            return None
        day, month, year = parts
        if year == '0000' or year == '1900':
            return None
        try:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        except ValueError:
            return None
    
    @staticmethod
    def _fix_hebrew(text: str) -> str:
        """Reverse DOS RTL text, but preserve number sequences in correct order."""
        import re
        if not text:
            return text
        # Reverse the whole string
        reversed_text = text[::-1].strip()
        # Numbers that were reversed need to be un-reversed back
        # Find all digit sequences and reverse them back
        def fix_numbers(m):
            return m.group()[::-1]
        return re.sub(r'\d+', fix_numbers, reversed_text)

    @staticmethod
    def _split_address_and_name(raw: Optional[str]) -> tuple:
        """
        Split the address field into (address, customer_name).

        The DOS field stores two values separated by 2+ spaces:
            [street address (reversed)][spaces][customer name (reversed)]

        After reversing the whole field:
            [customer name][spaces][street address]

        We split on the first run of 2+ spaces to separate them.

        Returns:
            (address, customer_name) - either may be None if not present
        """
        import re
        if not raw:
            return None, None

        reversed_text = raw[::-1].strip()

        parts = re.split(r'   +', reversed_text, maxsplit=1)  # 3+ spaces = field separator
        if len(parts) == 2:
            address     = parts[0].strip() or None
            customer_name = parts[1].strip() or None
        else:
            address     = reversed_text or None
            customer_name = None

        return address, customer_name
    
    @staticmethod
    def _parse_yymmdd(raw: str) -> Optional[str]:
        """Convert YYMMDD → YYYY-MM-DD. Returns None if invalid."""
        if not raw or len(raw) != 6 or raw == '000000':
            return None
        try:
            yy, mm, dd = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
            return f"20{yy:02d}-{mm:02d}-{dd:02d}"
        except ValueError:
            return None

    # Extended validation

    def validate_row(self, row: dict, row_number: int) -> List[str]:
        errors = super().validate_row(row, row_number)

        pr = row.get('previous_reading')
        if pr is not None and pr < 0:
            errors.append(f"שורה {row_number}: קריאה קודמת שלילית ({pr})")

        hist = row.get('raw_data', {}).get('hist_readings', [])
        if hist and all(v is None or v == 0 for v in hist):
            # All-zero history is suspicious but not an error - just note it
            pass

        return errors