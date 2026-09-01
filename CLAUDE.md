# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Monim V2** is a water meter reading management system for Israeli water corporations. Every two months, field readers visit meters and report readings. The system manages the full cycle: importing a corporation's meter file, splitting work into folders, assigning readers, collecting field readings, and exporting results.

All source code lives under `Monim V2/`. Commands below assume you `cd "Monim V2"` first.

---

## ⚠️ Claude Code Working Rules  

Claude Code operates under strict boundaries in this project:  
What you CAN do:

- Read any file in the project (backend included) to understand context
- Edit UI/frontend files: templates/, static/, routes/
- Create or modify Jinja2 templates, CSS, JavaScript, and route handlers

What you MUST NOT do:

- Never edit business logic files: src/services/, src/repositories/, database/, src/parsers/
- Never edit app.py, schema.sql, or test files under tests/
- Never change database queries, validation rules, or service orchestration
- Never modify .env or any configuration files

When in doubt:
If a task requires backend changes, stop and explain what needs to change and where - the developer (Dani) will implement it manually. You may suggest code, but do not write it directly to backend files.

---

## Setup & Running

```bash
cd "Monim V2"
pip install -r requirements.txt   # first time only
python app.py                     # Flask dev server (debug mode on)
```

The app runs on `http://localhost:5000`. It is a Hebrew RTL interface with six screens: Dashboard, Clients, Periods (file upload), Meters, Folders, Readers.

---

## Running Tests

Service tests are standalone scripts — run directly with Python:

```bash
cd "Monim V2"
python tests/services_tests/test_flow.py                    # End-to-end happy path (7 tests)
python tests/services_tests/test_client_errors.py          # Client validation (26 tests)
python tests/services_tests/test_period_errors.py          # ReadingPeriod (24 tests)
python tests/services_tests/test_source_file_errors.py     # PeriodSourceFile (17 tests)
python tests/services_tests/test_meter_errors.py           # PeriodMeter (20 tests)
python tests/services_tests/test_folder_errors.py          # FolderTemplate + WorkFolder (22 tests)
python tests/services_tests/test_reading_errors.py         # Reading (20 tests)
python tests/services_tests/test_shared_consumption.py

# Parser tests
python tests/parsing_tests/test_netanya_parser.py
python tests/parsing_tests/test_dos_parser.py
python tests/parsing_tests/test_process_uploaded_file.py
```

Tests use the `monim_v2_test` database (not the production `monim_v2` DB). Each test file imports `test_helpers.py` first, which sets `os.environ['DB_NAME'] = 'monim_v2_test'` before any DB import. The `cleanup()` helper re-runs `schema.sql` to reset the test DB to a clean state.

---

## Architecture: Four Layers

```
routes/               ← Flask blueprints: HTTP handling, template rendering, flash messages
src/services/         ← Business logic: validation, rules, orchestration
src/repositories/     ← Data access only: SQL + result mapping, no business logic
database/connection.py ← DB singleton + connection pool (psycopg2)

src/parsers/          ← File parsers: raw corporation Excel files → normalized rows
```

**Write rule:** Services call repositories for reads (SELECT). For writes (INSERT/UPDATE/DELETE), a service should only call other services, not repositories directly.

### Routes Layer (`routes/`)

Six Flask blueprints, one per screen. All service instances are shared singletons from `routes/shared.py`. Routes handle HTTP, call services, flash Hebrew success/error messages, and render Jinja2 templates. No business logic lives here.

`routes/shared.py` also holds the Hebrew label dicts (`WORK_STATUS_HE`, `FOLDER_STATUS_HE`, etc.) and `to_json_safe()` — a helper that converts `RealDictRow` to a JSON-serialisable dict (handles `date`, `Decimal`). Use it before passing DB rows to Jinja2 templates that embed data in `<script>` tags.

**HTML-embedded JSON pattern:** `meters.html` renders the full meter list as a JSON blob into a JS global (`ALL_METERS`) — always call `to_json_safe()` before passing such data from a route. `to_json_safe()` converts only **top-level** keys (flat dict); nested dicts or lists with `date`/`Decimal` values won't be converted. All six templates extend `templates/layout.html`.

Uploaded files land in `static/uploads/`. The only client-side script is `static/js/meters.js` (meters screen, ~646 lines — virtual scroll + filtering). All other screens are fully server-rendered.

**Mixed-response routes in meters blueprint:** Some meters routes return JSON directly (no redirect) — `GET /meters/<id>/estimate`, `POST /meters/<period_id>/bulk-estimate`, and `POST /meters/<id>/update-manager` (which calls `meter_service.apply_reading_to_current_state()`). These are called via `fetch` from `meters.js`. All other routes use the standard `redirect(url_for(...))` pattern.

**Logging:** App writes WARNING+ logs to `logs/monim.log` (rotating, 5 MB × 3 files) and to the console. The `logs/` directory is created automatically at startup. Services use `logging.getLogger(__name__)` — add `logger.warning(...)` or `logger.error(...)` for new error paths.

### Database Layer (`database/connection.py`)

`Database` is a singleton with a psycopg2 `SimpleConnectionPool`. Use:
- `db.execute_query(sql, params, fetch="one"|"all"|None, commit=True|False)` — for most CRUD
- `db.get_cursor(commit=True)` — context manager for multi-statement transactions
- `db.get_connection()` / `db.return_connection()` — raw pool access for bulk operations only
- `db.execute_script(path)` — runs a full `.sql` file (used to reset test DB)

### Repository Layer

One repository per table. Each instantiates `Database()` and works exclusively with `execute_query`. No business logic lives here.

### Service Layer

One service per entity. Each instantiates its own repository. Services validate input, enforce business rules, and call `repo.*` methods. The service raises `ValueError` (Hebrew message) on validation failure.

---

## Core Data Model

```
ReadingPeriod
   ├── PeriodSourceFile     (one per period — the uploaded Excel from the corporation)
   ├── PeriodMeters         (current state of each meter in the period)
   │       └── Readings     (all field reading events — append-only log)
   │               └── Photos
   ├── WorkFolders          (work bundles, based on FolderTemplates)
   └── FolderTemplates      (per-client templates: walk_order ranges → folder numbers)
FaultCodes                  (lookup table: code → Hebrew description, used on meters/readings)
```

**Key distinction:** `period_meters` stores the *latest state* of a meter (updated after each reading). `readings` stores the full *event history*. `previous_reading` appears in both — in `period_meters` it's the baseline from the source file (immutable); in `readings` it's the snapshot used at the time of that specific reading.

**`period_meters.raw_data`** is a JSONB column that preserves original source file fields. For Netanya meters it includes `hist_readings`: an array of 7 historical reading values (indices 0–6 = q1–q7, most-recent first). Index 5 (q6) and 6 (q7) are used by `calculate_estimate()` to derive the parallel-period consumption for estimation.

**`period_meters.addon`** stores extra consumption for stopped meters (fault_code `'1'`): the q6 parallel-period diff is billed as an add-on rather than folded into `consumption`.

**Status flows:**

| Entity | States |
|---|---|
| ReadingPeriod | `pending → file_received → active → completed` (or `skipped`) |
| PeriodSourceFile | `pending → success` or `pending → error → pending` |
| PeriodMeter (work_status) | `new → assigned_to_folder → assigned_to_reader → in_progress → completed` or `→ exception` |
| WorkFolder | `pending → assigned → in_progress → completed` |
| Reading | `submitted → approved` or `submitted → requires_review → approved/rejected/recheck` |

---

## Shared Consumption

`SharedConsumptionService.calculate(period_id, folder_id=None, include_details=False)` distributes 
a building's general-meter (usage_type `1`) consumption across its apartment meters (usage_type `5`).

Meters are grouped by `meter_id[:8]` (`[4-digit street][4-digit building]`) — not by `address`, since 
the `street apartment/building` format caused false collisions between unrelated buildings.

Negative results mark the general meter as `exception` (self-clearing on the next successful run); 
missing reading data skips the building silently. `include_details=False` by default — the 
`POST /meters/<period_id>/shared-consumption` route only needs summary counts; scripts/debugging 
can pass `True` for a full per-building breakdown.
---

## Parsers

Each corporation has its own parser in `src/parsers/` that extends `BaseParser`. Implement two abstract methods: `parse(file_path) → List[dict]` and `get_file_type() → str`.

The normalized row dict format:
```python
{
    'row_number': int,         # required : source file row ID
    'meter_number': str,       # required
    'customer_number': str,    # optional
    'customer_name': str,      # optional
    'address': str,            # optional
    'walk_order': int,         # optional : used for folder assignment
    'previous_reading': float, # optional
    'installation_date': str,  # optional : YYYY-MM-DD
    'raw_data': dict,          # optional : keep original fields for traceability
}
```

Rows missing `meter_number` are skipped. Rows missing optional fields get `work_status = 'missing_info'` with `raw_data.missing_fields` listing what's absent. If fewer than 5% of rows are skipped the file status is `success`; otherwise `partial`.

The existing `NetanyaParser` (for מי נתניה) is the reference implementation. Handles 52K rows in ~5 seconds.

---

## Environment

Database credentials are in `Monim V2/.env`:
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=monim_v2          # production
DB_USER=postgres
DB_PASSWORD=...
```

Test runs override `DB_NAME` to `monim_v2_test` via `os.environ` before importing the DB module.

---

## Demo Script

`scripts/demo_run.py` runs a full end-to-end flow against `monim_v2_test`: creates a client, reader, period, uploads and processes a file, creates templates and folders, assigns a reader, submits and approves a reading. Use it to understand how the layers fit together.

---

## Known TODOs in Services

- `client_service` / `reader_service`: dependency check before delete (currently relies on DB CASCADE)
- `periodmeter_service`: validate period membership when assigning meter to folder
- `workfolder_service`: optimize completed-count query
- `reading_service`: enforce photo requirement for exception readings
