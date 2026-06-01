-- standards
-- One row per standard. No embeddings here.
CREATE TABLE standards (
    id                  TEXT PRIMARY KEY,    -- "CCSS.MATH.6.RP.A.3"
    system              TEXT NOT NULL,       -- "ccss" | "sg-moe" | "ib-myp"
    subject             TEXT NOT NULL,       -- always "mathematics" in v1
    grade               TEXT NOT NULL,       -- "6"
    grade_band          TEXT,               -- "6-8" where applicable; NULL if single grade
    domain              TEXT NOT NULL,       -- "Ratios and Proportional Relationships"
    cluster             TEXT,               -- CCSS-specific; NULL for other systems
    standard_text       TEXT NOT NULL,       -- verbatim official text
    last_verified_date  TEXT NOT NULL,       -- ISO 8601 "2026-05-30"
    source_url          TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_standards_system  ON standards(system);
CREATE INDEX idx_standards_grade   ON standards(system, grade);
CREATE INDEX idx_standards_domain  ON standards(system, domain);


-- sub_standards
-- Child records — 6.RP.A.3a, 3b, 3c, 3d
CREATE TABLE sub_standards (
    id          TEXT PRIMARY KEY,            -- "CCSS.MATH.6.RP.A.3a"
    parent_id   TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    system      TEXT NOT NULL,
    text        TEXT NOT NULL,
    position    INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_sub_standards_parent ON sub_standards(parent_id);


-- standard_relationships
-- Within-system links: prerequisites and successors
CREATE TABLE standard_relationships (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    target_id    TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,             -- "prerequisite" | "successor"
    system       TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, relationship)
);

CREATE INDEX idx_relationships_source ON standard_relationships(source_id);
CREATE INDEX idx_relationships_target ON standard_relationships(target_id);


-- keywords
-- Many-to-one: each keyword links to one standard
CREATE TABLE keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    standard_id TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(standard_id, keyword)
);

CREATE INDEX idx_keywords_standard ON keywords(standard_id);
CREATE INDEX idx_keywords_keyword  ON keywords(keyword);


-- embeddings
-- Separate table — re-embeddable without touching standards data
CREATE TABLE embeddings (
    standard_id   TEXT PRIMARY KEY REFERENCES standards(id) ON DELETE CASCADE,
    model         TEXT NOT NULL,            -- "nomic-embed-text"
    model_version TEXT,
    vector        BLOB NOT NULL,            -- numpy.tobytes()
    dimensions    INTEGER NOT NULL,         -- 768 for nomic-embed-text
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);


-- crosswalk_mappings
-- Cross-country standard translations
CREATE TABLE crosswalk_mappings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    target_id           TEXT NOT NULL REFERENCES standards(id) ON DELETE CASCADE,
    source_system       TEXT NOT NULL,
    target_system       TEXT NOT NULL,
    relationship        TEXT NOT NULL,      -- "equivalent" | "overlapping" | "adjacent"
    confidence_score    REAL NOT NULL,      -- 0.0–1.0
    grade_delta         INTEGER NOT NULL,   -- 0 = same; +1 = target one year later
    notes               TEXT,
    verified_by_human   INTEGER NOT NULL DEFAULT 0,
    verified_by         TEXT,
    verified_date       TEXT,
    flagged_for_review  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id)
);

CREATE INDEX idx_crosswalk_source   ON crosswalk_mappings(source_id);
CREATE INDEX idx_crosswalk_target   ON crosswalk_mappings(target_id);
CREATE INDEX idx_crosswalk_systems  ON crosswalk_mappings(source_system, target_system);
CREATE INDEX idx_crosswalk_verified ON crosswalk_mappings(verified_by_human);
CREATE INDEX idx_crosswalk_flagged  ON crosswalk_mappings(flagged_for_review);
