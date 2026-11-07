-- knowledge.db — the DURABLE store. Back this file up.
-- Holds user decisions and everything needed to explain them: entities, claims, evidence,
-- labels, schema versions and the append-only event ledger.
--
-- Ledger-tracked tables use a single TEXT primary key named `id` and no cascading foreign keys,
-- so that undo can restore any row snapshot without fighting constraint ordering.

CREATE TABLE settings (
  id    TEXT PRIMARY KEY,           -- setting key, e.g. "cloud.enabled"
  value TEXT NOT NULL               -- JSON
);

CREATE TABLE schema_versions (
  id         TEXT PRIMARY KEY,
  version    INTEGER NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  definition TEXT NOT NULL,         -- JSON of SchemaDef
  created_at TEXT NOT NULL
);

CREATE TABLE roots (                -- files/folders the user selected
  id         TEXT PRIMARY KEY,
  path       TEXT NOT NULL UNIQUE,
  kind       TEXT NOT NULL CHECK (kind IN ('file', 'folder')),
  watch      INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE sources (              -- one row per file; originals are never modified
  id           TEXT PRIMARY KEY,
  root_id      TEXT,
  path         TEXT NOT NULL UNIQUE,
  kind         TEXT NOT NULL,
  size         INTEGER NOT NULL DEFAULT 0,
  mtime        REAL NOT NULL DEFAULT 0,
  content_hash TEXT,
  indexed_hash TEXT,                -- hash at last successful index; equal => skip (FR-1)
  status       TEXT NOT NULL,
  error        TEXT,
  priority     INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE INDEX sources_root ON sources(root_id);

CREATE TABLE entities (
  id          TEXT PRIMARY KEY,
  type        TEXT NOT NULL,
  name        TEXT NOT NULL,
  status      TEXT NOT NULL,        -- auto | verified | rejected | merged
  created_by  TEXT NOT NULL,        -- "user" | "model:<id>" | "voice" | "import"
  merged_into TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX entities_type ON entities(type, status);

CREATE TABLE aliases (
  id         TEXT PRIMARY KEY,
  entity_id  TEXT NOT NULL,
  alias      TEXT NOT NULL,
  normalized TEXT NOT NULL,
  origin     TEXT NOT NULL,         -- name | user | merge | model
  created_at TEXT NOT NULL,
  UNIQUE (entity_id, normalized)
);
CREATE INDEX aliases_normalized ON aliases(normalized);

CREATE TABLE claims (
  id             TEXT PRIMARY KEY,
  subject_id     TEXT NOT NULL,
  predicate      TEXT NOT NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('attribute', 'relation')),
  value          TEXT,              -- JSON literal for attributes
  object_id      TEXT,              -- entity id for relations
  valid_from     TEXT,
  valid_to       TEXT,
  confidence     REAL NOT NULL,
  status         TEXT NOT NULL,     -- proposed | verified | rejected
  extractor      TEXT NOT NULL,     -- JSON Extractor (who/what, model, prompt version)
  fingerprint    TEXT NOT NULL,
  label_id       TEXT,
  needs_review   INTEGER NOT NULL DEFAULT 0,
  schema_version INTEGER,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX claims_subject ON claims(subject_id);
CREATE INDEX claims_object ON claims(object_id);
CREATE INDEX claims_fingerprint ON claims(fingerprint);
CREATE INDEX claims_status ON claims(status, confidence);
CREATE INDEX claims_valid_from ON claims(valid_from);

CREATE TABLE evidence (
  id         TEXT PRIMARY KEY,
  claim_id   TEXT NOT NULL,
  source_id  TEXT,                  -- file the evidence is in (NULL for pure label evidence)
  chunk_id   TEXT,                  -- soft link into index.db; may dangle after a rebuild
  locator    TEXT NOT NULL,         -- JSON Locator: survives index rebuilds
  quote      TEXT NOT NULL,         -- the exact span text
  label_id   TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX evidence_claim ON evidence(claim_id);
CREATE INDEX evidence_source ON evidence(source_id);

CREATE TABLE labels (               -- voice or typed labels
  id          TEXT PRIMARY KEY,
  transcript  TEXT NOT NULL,
  audio_path  TEXT,
  target_kind TEXT NOT NULL,
  target_ids  TEXT NOT NULL,        -- JSON list
  parsed      TEXT NOT NULL,        -- JSON ParsedLabel (ops + questions)
  status      TEXT NOT NULL,        -- preview | committed | cancelled
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------------------------
-- Event ledger (append-only). One group per user/model action; one event per row change.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE event_groups (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  id      TEXT NOT NULL UNIQUE,
  ts      TEXT NOT NULL,
  actor   TEXT NOT NULL,            -- "user" | "model:<id>" | "system" | "voice"
  action  TEXT NOT NULL,            -- e.g. "entity.merge", "claim.verify", "undo"
  summary TEXT NOT NULL DEFAULT '',
  undoes  TEXT                      -- group id this group reverts (for undo/redo)
);

CREATE TABLE events (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  id       TEXT NOT NULL UNIQUE,
  group_id TEXT NOT NULL,
  ts       TEXT NOT NULL,
  tbl      TEXT NOT NULL,
  row_id   TEXT NOT NULL,
  op       TEXT NOT NULL CHECK (op IN ('insert', 'update', 'delete')),
  before   TEXT,                    -- JSON row snapshot (NULL for insert)
  after    TEXT                     -- JSON row snapshot (NULL for delete)
);
CREATE INDEX events_row ON events(tbl, row_id);
CREATE INDEX events_group ON events(group_id);

CREATE TRIGGER events_append_only_u BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_append_only_d BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER groups_append_only_u BEFORE UPDATE ON event_groups
BEGIN SELECT RAISE(ABORT, 'event groups are append-only'); END;
CREATE TRIGGER groups_append_only_d BEFORE DELETE ON event_groups
BEGIN SELECT RAISE(ABORT, 'event groups are append-only'); END;
