CREATE TABLE packages (
    name TEXT PRIMARY KEY,
    loong_ver TEXT,
    x86_ver TEXT,
    repo TEXT,
    build_status TEXT
);

CREATE TABLE logs (
    name TEXT,
    operation TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    result TEXT
);
