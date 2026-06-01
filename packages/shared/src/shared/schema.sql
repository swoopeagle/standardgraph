CREATE TABLE IF NOT EXISTS standards (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'CCSS',
    grade           TEXT,
    domain_code     TEXT,
    domain          TEXT,
    cluster_letter  TEXT,
    cluster         TEXT,
    description     TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sub_standards (
    id          TEXT PRIMARY KEY,
    standard_id TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    order_idx   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS standard_relationships (
    from_id           TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    to_id             TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    weight            REAL DEFAULT 1.0,
    PRIMARY KEY (from_id, to_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    standard_id TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL,
    weight      REAL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_keywords_standard ON keywords(standard_id);
CREATE INDEX IF NOT EXISTS idx_keywords_keyword  ON keywords(keyword);

CREATE TABLE IF NOT EXISTS embeddings (
    standard_id TEXT PRIMARY KEY REFERENCES standards(id) ON DELETE CASCADE,
    model       TEXT NOT NULL DEFAULT 'nomic-embed-text',
    vector      BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS crosswalk_mappings (
    from_id          TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    to_id            TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    similarity_score REAL NOT NULL,
    method           TEXT DEFAULT 'semantic',
    notes            TEXT,
    PRIMARY KEY (from_id, to_id)
);
