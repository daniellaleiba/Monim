-- Monim : schema.sql 

-- Deleting tables (if exists)
DROP TABLE IF EXISTS photos CASCADE;
DROP TABLE IF EXISTS readings CASCADE;
DROP TABLE IF EXISTS work_folders CASCADE;
DROP TABLE IF EXISTS folder_templates CASCADE;
DROP TABLE IF EXISTS period_meters CASCADE;
DROP TABLE IF EXISTS period_source_files CASCADE;
DROP TABLE IF EXISTS reading_periods CASCADE;
DROP TABLE IF EXISTS readers CASCADE;
DROP TABLE IF EXISTS clients CASCADE;
DROP TABLE IF EXISTS fault_codes CASCADE;

-- client
CREATE TABLE clients (
    client_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    corporation_number VARCHAR(20) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    city VARCHAR(50)
);


-- readers
CREATE TABLE readers (
    reader_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- reading_periods
-- reading periods usually: 2 Months 
CREATE TABLE reading_periods (
    period_id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    period_number INTEGER NOT NULL CHECK (period_number BETWEEN 1 AND 6),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'file_received', 'active', 'completed','skipped')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CHECK (start_date < end_date),
    UNIQUE (client_id, year, period_number)

);

-- period_source_files
-- The official source file uploaded for a reading period
-- Supports version history per period
CREATE TABLE period_source_files (
    source_file_id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES reading_periods(period_id) ON DELETE CASCADE,
    
    -- File metadata
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255),
    file_path VARCHAR(500),
    file_type VARCHAR(50) NOT NULL DEFAULT 'excel', -- טיפוס הקובץ מהתאגיד

    rows_count INTEGER CHECK (rows_count IS NULL OR rows_count >= 0),
    processing_status VARCHAR(30) NOT NULL DEFAULT 'pending' 
        CHECK (processing_status IN ('pending', 'success', 'error', 'partial')),
    error_message TEXT,

    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    uploaded_by VARCHAR(50), -- work manager / operator name or username

    UNIQUE(period_id)
);


-- period_meters
-- The main business entity: one meter row inside a specific period
CREATE TABLE period_meters (
    period_meter_id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES reading_periods(period_id) ON DELETE CASCADE,
    source_file_id INTEGER REFERENCES period_source_files(source_file_id) ON DELETE RESTRICT, -- NULL for meters added in the field
    folder_id INTEGER, -- referance later (on alter table)

    -- Identity (from source file)
    meter_number      VARCHAR(50)    NOT NULL,
    row_number        INTEGER        CHECK (row_number > 0), -- row in original file, for debugging; NULL for meters added in the field
    customer_number   VARCHAR(50),
    customer_name     VARCHAR(100),
    address           VARCHAR(100),
    walk_order        BIGINT,
    installation_date DATE,
    previous_reading  NUMERIC(12,3),
    raw_data          JSONB,

    -- Work state (managed by system)
    work_status VARCHAR(30) NOT NULL DEFAULT 'new'
            CHECK (work_status IN ('new', 'assigned_to_folder', 'assigned_to_reader', 'in_progress', 'completed', 'exception','missing_info')), -- assigned/ in_progress / completed / exception
    current_fault_code   VARCHAR(50), -- fault code if applicable

    -- Reading result (final values for export)
    current_reading NUMERIC(12,3),
    consumption     NUMERIC(12,3),
    addon           NUMERIC(12,3), -- extra consumption for stopped meters (fault_code=1)
    is_estimated  BOOLEAN DEFAULT FALSE,
    shared_consumption NUMERIC(12,3),
    reading_time TIMESTAMP,

    -- Manager notes
    manager_notes TEXT,
   
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Origin: from the source file, or added by a reader in the field
    added_in_field BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK ((added_in_field AND source_file_id IS NULL AND row_number IS NULL)
        OR (NOT added_in_field AND source_file_id IS NOT NULL AND row_number IS NOT NULL)),
    UNIQUE (period_id, meter_number)
);

-- folder_templates
-- מבנה תיק מטווחי סדר הליכה: קבוע לאורך השנה
CREATE TABLE folder_templates (
    template_id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(client_id) ON DELETE CASCADE,
    folder_number INTEGER NOT NULL,
    folder_name VARCHAR(100),
    walk_order_start BIGINT,
    walk_order_end BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(client_id, folder_number)
);

-- work_folders
-- Actual work folders created for a specific period
CREATE TABLE work_folders (
    folder_id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES reading_periods(period_id) ON DELETE CASCADE, -- קישור לתקופה
    template_id INTEGER NOT NULL REFERENCES folder_templates(template_id) ON DELETE RESTRICT, -- קישור לתבנית
    
    status VARCHAR(30) NOT NULL DEFAULT 'pending'
         CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed')),
    assigned_to INTEGER REFERENCES readers(reader_id) ON DELETE SET NULL,

    total_meters INTEGER NOT NULL DEFAULT 0 CHECK (total_meters >= 0),
    completed_meters INTEGER NOT NULL DEFAULT 0 CHECK (completed_meters >= 0 AND completed_meters <= total_meters),
   
    assigned_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Release to the reader's mobile app (only the last release is kept)
    released_at TIMESTAMP,                                  -- When the manager last released it
    include_previous_readings BOOLEAN NOT NULL DEFAULT TRUE, -- Send previous readings to the app
    downloaded_at TIMESTAMP,                                -- When the app downloaded it, since the last release


    UNIQUE(period_id, template_id),
    UNIQUE (folder_id, period_id)
);
ALTER TABLE period_meters
ADD CONSTRAINT fk_period_meters_folder_same_period
FOREIGN KEY (folder_id, period_id)
REFERENCES work_folders(folder_id, period_id)
ON DELETE RESTRICT;


-- readings
-- Field reading result for a period meter
CREATE TABLE readings (
    reading_id SERIAL PRIMARY KEY,
    period_meter_id INTEGER NOT NULL REFERENCES period_meters(period_meter_id) ON DELETE CASCADE,
    reader_id INTEGER REFERENCES readers(reader_id) ON DELETE SET NULL,

    previous_reading NUMERIC(12,3),      -- Snapshot of the meter's baseline at reading time
    current_reading NUMERIC(12,3),       -- NULL only for a no-reading
    consumption NUMERIC(12,3),
    is_no_reading BOOLEAN NOT NULL DEFAULT FALSE, -- The reader could not read the meter
    first_attempt_reading NUMERIC(12,3), -- Value entered before re-verifying an exception

    fault_code VARCHAR(50),              -- Chosen by the reader
    exception_type VARCHAR(30)           -- Detected by the app; NULL = no exception
        CHECK (exception_type IN ('high', 'low', 'same', 'lower_than_previous')),
    notes TEXT,                          -- The reader's notes (manager notes live on period_meters)
    photo_missing BOOLEAN NOT NULL DEFAULT FALSE, -- A photo was taken but its file was lost on the device

    reading_status VARCHAR(30) NOT NULL DEFAULT 'submitted'
        CHECK (reading_status IN ('submitted', 'requires_review', 'approved', 'rejected', 'recheck')),

    reading_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, -- When the reading was taken in the field
    transmitted_at TIMESTAMP,                                   -- When it reached the server
    version_id VARCHAR(36) UNIQUE,       -- UUID from the mobile app; NULL for other readings

    CHECK ((is_no_reading AND current_reading IS NULL)
        OR (NOT is_no_reading AND current_reading IS NOT NULL))
);

-- photos
-- Photos attached to readings
CREATE TABLE photos (
    photo_id SERIAL PRIMARY KEY,
    reading_id INTEGER NOT NULL REFERENCES readings(reading_id) ON DELETE CASCADE,
    photo_path VARCHAR(500) NOT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP 
);

-- fault codes
CREATE TABLE fault_codes (
    code VARCHAR(10) PRIMARY KEY,
    description VARCHAR(100) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Indexes

-- periods
CREATE INDEX idx_periods_client ON reading_periods(client_id);

-- period meters
CREATE INDEX idx_period_meters_walk_order ON period_meters(walk_order);
CREATE INDEX idx_period_meters_folder ON period_meters(folder_id);
CREATE INDEX idx_period_meters_status ON period_meters(period_id, work_status);

-- folders
CREATE INDEX idx_work_folders_period ON work_folders(period_id);
CREATE INDEX idx_work_folders_reader ON work_folders(assigned_to);

-- readings
CREATE INDEX idx_readings_period_meter ON readings(period_meter_id);
CREATE INDEX idx_readings_reader ON readings(reader_id);

-- photos
CREATE INDEX idx_photos_reading ON photos(reading_id);


-- נתוני דמה
-- TODO: password_hash כאן הוא טקסט גולמי, לא hash אמיתי להחליף לפני login אמיתי.
INSERT INTO clients (name, corporation_number) VALUES ('עיריית נתניה', '510283418'),('עיריית תל אביב', '500038937');
INSERT INTO readers (name, username, password_hash) VALUES ('שמעון כהן', 'shimon', 'scrypt:32768:8:1$6I1XPgz7F4QEbJGT$eb885d1c51d6d31224c3e2ae2f7e6315369adf31c6655249371c8c72e7c7f466c8244afd6ba2e0cfa53573f9936373fa27676cf2f5e1d357ad57da370f2448c7'),
            ('עדן לוי', 'eden', 'scrypt:32768:8:1$7pQdR73EefYecsUZ$a42da2c64934a919b94d6112be978ce33ec52b85443bea8ba75f305996c83555e44ba6aa42c1c6bf7a45d13f0b9b1d7f22e1a21d341b9262675df003a188fbdd');

-- Fault codes initial data
INSERT INTO fault_codes (code, description) VALUES
    ('1',  'מונה עצור'),
    ('2',  'מונה שבור'),
    ('3',  'מד לא קריא ירקת'),
    ('4',  'מד הפוך פיזית'),
    ('5',  'מד מסובב לא ניתן לקרוא'),
    ('6',  'מונה מזייף'),
    ('7',  'אין שינוי בקריאה'),
    ('8',  'אין גישה מד נעול על הגג'),
    ('9',  'מכוסה בטון'),
    ('10', 'אין גישה מד בתוך הנכס'),
    ('11', 'מונה קבור'),
    ('12', 'אין גישה'),
    ('13', 'כלב'),
    ('14', 'שיחים לגזום'),
    ('15', 'סגור בארגז'),
    ('16', 'מיקום מונה לא ידוע'),
    ('17', 'חיבור ללא מד'),
    ('19', 'אין גישה קבור בתוך בריכה'),
    ('20', 'אין גישה מד סגור בחצר'),
    ('21', 'שיבר סגור'),
    ('22', 'נזילה אחרי המד'),
    ('23', 'מד לא קריא אדים'),
    ('24', 'מונה הוחלף'),
    ('25', 'אדים קריאה לא בטוחה'),
    ('26', 'שיבר נוזל'),
    ('27', 'פורק'),
    ('28', 'טעות בקריאה הקודמת'),
    ('29', 'אין שימוש'),
    ('30', 'צריכה גבוהה'),
    ('33', 'קריאה ע"י התושב'),
    ('36', 'טעות בערכה קודמת'),
    ('42', 'קריאה בדוקה'),
    ('46', 'מספר מד לא תואם'),
    ('51', 'קריאה בטוחה בשל צריכה גבוהה'),
    ('52', 'קריאה בטוחה בשל צריכה נמוכה'),
    ('54', 'מד חדש'),
    ('59', 'פרפר מסתובב אחורה'),
    ('60', 'מד כבוי'),
    ('63', 'הצלבה עם השכן'),
    ('75', 'סגור עזוב'),
    ('83', 'מגנט')
ON CONFLICT (code) DO NOTHING;
