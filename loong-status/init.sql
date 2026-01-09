CREATE TABLE IF NOT EXISTS packages (
    name TEXT PRIMARY KEY,
    base TEXT,
    repo TEXT,
    x86_version TEXT,
    x86_testing_version TEXT,
    x86_staging_version TEXT,
    loong_version TEXT,
    loong_testing_version TEXT,
    loong_staging_version TEXT,
    flags INTEGER,
    timecost INTEGER,
    log_version TEXT,
);
CREATE TABLE IF NOT EXISTS last_update (
    last_update TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    pkgbase TEXT,
    builder INTEGER,
    build_result INTEGER,
    build_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    taskno INTEGER,
    pkgbase TEXT,
    tasklist INTEGER,
    info TEXT,
    repo INTEGER,
    taskid INTEGER,
    logid INTEGER
);

CREATE TABLE IF NOT EXISTS builder (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    cpu TEXT,
    ram INTEGER,
    storage INTEGER,
    ip TEXT,
    time_scale REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS grouplist (
    id SERIAL PRIMARY KEY,
    base TEXT NOT NULL,
    group_name TEXT NOT NULL,
    info TEXT
);
