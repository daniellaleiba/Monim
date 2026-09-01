"""
Generates dos_sample.D: a small, PII-redacted fixture for testing NetanyaDParser (fixed-width DOS format).
 
Instead of synthetic/fabricated rows, this samples 10 real rows spread across an actual production-format .D file (evenly spaced, not just
the first N, for realistic field diversity), then replaces all personally-identifying fields (customer name, address, customer
number, meter number, physical_number, meter_id, meter_location remarks) with realistic fake values instead of the real ones.
Everything else (walk_order, readings, dates, usage_type) is left as real data, since these are non-identifying operational values.
 
Run manually, once, whenever the fixture needs refreshing. Not part of the automated test suite.
"""

import argparse
import os
import random
import re
import sys

# --- Real field offsets, copied from src/parsers/netanya_d_parser.py's _F dict ---
FIELDS = {
    'meter_id':          (10, 21),
    'customer_name_raw': (21, 41),
    'address':           (41, 61),
    'meter_location':    (61, 81),
    'customer_number':   (102, 111),
    'physical_number':   (116, 126),
    'meter_number':      (495, 503),
}
WALK_ORDER_PRIMARY = (86, 96)
DEAD_ZONE = (342, 380)  # docstring calls this "Location name" but _parse_line() never reads it

FAULT_CODES_FALLBACK = [ "מונה עצור", "מונה שבור", "אין גישה", "כלב", "מונה קבור", "שיבר סגור", "צריכה גבוהה", "אין שימוש", "מד חדש",]

FAKE_FIRST_NAMES = ["דוד", "משה", "רחל", "שרה", "יוסף", "מרים", "אברהם", "לאה", "יעקב", "רבקה"]
FAKE_LAST_NAMES = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "אזולאי", "דהן", "אוחיון", "טל", "שגיא"]
FAKE_STREET_NAMES = ["הרצל", "ויצמן", "רוטשילד", "בן גוריון", "האלון", "ההדס", "היובל", "הגפן"]
FAKE_CITIES = ["נתניה", "כפר ידידיה", "פרדס חנה", "אבן יהודה"]

DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'tests', 'parsing_tests', 'test_data', 'dos_sample.D')
DEFAULT_SCHEMA_SQL = os.path.join(os.path.dirname(__file__), '..', 'schema.sql')


# --- RTL encode/decode, mirroring netanya_d_parser.py exactly ---

def fix_hebrew(text):
    """Exact copy of NetanyaDParser._fix_hebrew, used here only to
    self-verify our encoder round-trips correctly before writing."""
    if not text:
        return text
    reversed_text = text[::-1].strip()
    def fix_numbers(m):
        return m.group()[::-1]
    return re.sub(r'\d+', fix_numbers, reversed_text)

def flip_digit_runs(s):
    def flip(m):
        return m.group()[::-1]
    return re.sub(r'\d+', flip, s)

def encode_hebrew(readable_text):
    """Inverse of fix_hebrew: encodes a normal readable string into the
    raw DOS RTL storage form. raw = reverse(flip_digit_runs(R))."""
    return flip_digit_runs(readable_text)[::-1]

def self_test_encoding():
    """Sanity check the encoder against the real parser's exact decode logic."""
    samples = ["מונה עצור", "כלב", "רחל כהן", "הרצל 12", "מיקוד: 4200000 נתניה"]
    for s in samples:
        encoded = encode_hebrew(s)
        decoded = fix_hebrew(encoded)
        assert decoded == s, f"Round-trip failed for {s!r}: got {decoded!r}"

# --- Sampling from the real source file ---

def sample_real_rows(source_path, num_rows):
    with open(source_path, "rb") as f:
        raw = f.read()

    lines = raw.split(b'\r\n')
    if len(lines) == 1:
        lines = raw.split(b'\n')

    all_data_lines = [l for l in lines if len(l) >= 495]
    print(f"סה\"כ שורות תקינות בקובץ המקור: {len(all_data_lines)}")

    step = max(1, len(all_data_lines) // num_rows)
    sampled = all_data_lines[::step][:num_rows]
    print(f"נבחרו {len(sampled)} שורות, כל שורה {step}-ית")
    return sampled

def has_usable_primary_walk_order(line_bytes):
    """True if the primary walk_order field is non-zero, meaning the
    fallback field (which overlaps meter_id) is never actually read by
    the parser for this row - safe to fake meter_id in that shared byte
    range without risking corrupting a value the parser would use."""
    s, e = WALK_ORDER_PRIMARY
    try:
        text = line_bytes[s:e].decode('cp862', errors='replace').strip()
        return bool(text) and int(text) != 0
    except ValueError:
        return False

# --- Fake value generators ---

def fake_numeric_field(rng, width):
    n = rng.randint(10 ** (width - 2), 10 ** (width - 1) - 1)
    return str(n).zfill(width)

def fake_alnum_field(rng, width):
    return "".join(rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(width))

def fake_name(rng):
    return f"{rng.choice(FAKE_FIRST_NAMES)} {rng.choice(FAKE_LAST_NAMES)}"

def fake_address_short(rng):
    return f"{rng.choice(FAKE_STREET_NAMES)} {rng.randint(1, 90)}"

def fake_meter_location(rng, fault_descriptions, blank_probability=0.3):
    if rng.random() < blank_probability:
        return None
    return rng.choice(fault_descriptions)

def fake_dead_zone_address(rng, max_width):
    for _ in range(20):
        postal = rng.randint(1, 999999)
        city = rng.choice(FAKE_CITIES)
        street = rng.choice(FAKE_STREET_NAMES)
        number = rng.randint(1, 90)
        text = f"מיקוד: {postal} {city} {street} {number}"
        if len(text) <= max_width:
            return text
    raise RuntimeError("Could not generate a dead-zone address short enough to fit the field.")

def write_field(line, start, end, value, align='left'):
    """Write `value` into line[start:end], space-padded to exact width.
    Raises rather than truncates: for RTL-encoded fields, truncating
    the encoded string chops from the wrong end relative to the
    readable text, garbling the START of the word instead of the end."""
    width = end - start
    if len(value) > width:
        raise ValueError(f"value {value!r} ({len(value)} chars) exceeds field width {width} "
                          f"at bytes ({start},{end}) - truncation would corrupt RTL-encoded text")
    padded = value.ljust(width) if align == 'left' else value.rjust(width)
    return line[:start] + padded + line[end:]

def clear_field(line, start, end):
    return line[:start] + (' ' * (end - start)) + line[end:]

def load_fault_descriptions(sql_path, max_width):
    try:
        with open(sql_path, encoding='utf-8') as f:
            content = f.read()
    except OSError:
        print(f"WARNING: couldn't read {sql_path}, using built-in fallback fault descriptions.", file=sys.stderr)
        pool = FAULT_CODES_FALLBACK
    else:
        matches = re.findall(r"\('\d+',\s*'([^']+)'\)", content)
        pool = matches if matches else FAULT_CODES_FALLBACK

    fitting = [d for d in pool if len(d) <= max_width]
    dropped = [d for d in pool if len(d) > max_width]
    if dropped:
        print(f"NOTE: dropped {len(dropped)} fault_codes descriptions too long for the "
              f"{max_width}-char meter_location field: {dropped}", file=sys.stderr)
    return fitting

def anonymize_row(raw_line, rng, fault_descriptions, used_customer_numbers, used_meter_numbers):
    line = raw_line.decode('cp862', errors='replace')

    s, e = FIELDS['meter_id']
    line = write_field(line, s, e, fake_numeric_field(rng, e - s), align='right')

    s, e = FIELDS['customer_name_raw']
    line = write_field(line, s, e, encode_hebrew(fake_name(rng)), align='left')

    s, e = FIELDS['address']
    line = write_field(line, s, e, encode_hebrew(fake_address_short(rng)), align='left')

    s, e = FIELDS['meter_location']
    loc = fake_meter_location(rng, fault_descriptions)
    line = clear_field(line, s, e) if loc is None else write_field(line, s, e, encode_hebrew(loc), align='left')

    s, e = FIELDS['customer_number']
    val = fake_numeric_field(rng, e - s)
    while val in used_customer_numbers:
        val = fake_numeric_field(rng, e - s)
    used_customer_numbers.add(val)
    line = write_field(line, s, e, val, align='right')

    s, e = FIELDS['physical_number']
    line = write_field(line, s, e, fake_numeric_field(rng, e - s), align='right')

    s, e = FIELDS['meter_number']
    val = fake_alnum_field(rng, e - s)
    while val in used_meter_numbers:
        val = fake_alnum_field(rng, e - s)
    used_meter_numbers.add(val)
    line = write_field(line, s, e, val, align='left')

    s, e = DEAD_ZONE
    line = write_field(line, s, e, encode_hebrew(fake_dead_zone_address(rng, e - s)), align='left')

    return line.encode('cp862')

def main():
    parser = argparse.ArgumentParser(description="Sample real rows from a production .D file and fully anonymize them.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed (default: 7)")
    parser.add_argument("--num-rows", type=int, default=10, help="Rows to sample (default: 10)")
    parser.add_argument("--fault-codes-sql", default=DEFAULT_SCHEMA_SQL,
                         help=f"Path to schema.sql for realistic fault/remark text (default: {DEFAULT_SCHEMA_SQL})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()

    source = os.environ.get("DOS_SOURCE_FILE")
    if not source:
        print("הגדירי משתנה סביבה DOS_SOURCE_FILE עם הנתיב לקובץ המקור")
        sys.exit(1)

    self_test_encoding()

    rng = random.Random(args.seed)
    meter_location_width = FIELDS['meter_location'][1] - FIELDS['meter_location'][0]
    fault_descriptions = load_fault_descriptions(args.fault_codes_sql, meter_location_width)

    sampled_lines = sample_real_rows(source, args.num_rows)

    used_customer_numbers, used_meter_numbers = set(), set()
    output_lines = []
    skipped = 0
    for line_bytes in sampled_lines:
        if not has_usable_primary_walk_order(line_bytes):
            # meter_id's byte range overlaps the walk_order fallback field;
            # skip rows that would actually need that fallback rather than
            # risk faking over a value the parser would read.
            skipped += 1
            continue
        output_lines.append(anonymize_row(line_bytes, rng, fault_descriptions, used_customer_numbers, used_meter_numbers))

    if skipped:
        print(f"דילגתי על {skipped} שורות שהיו תלויות ב-walk_order fallback (כדי לא לפגוע בערך שהפרסר קורא בפועל)")

    with open(args.output, "wb") as f:
        f.write(b"\r\n".join(output_lines))

    print(f"נכתבו {len(output_lines)} שורות מנוקות ומוחלפות בדאטה דמה ל-{args.output}")


if __name__ == "__main__":
    main()