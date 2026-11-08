-- index.db — the DISPOSABLE store. Everything here can be rebuilt from the files plus the
-- knowledge store. Deleting this file is always safe; the app re-indexes in the background.
-- The durable knowledge (entities, claims, labels, ledger) lives in MongoDB.

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE chunks (
  id           TEXT PRIMARY KEY,
  source_id    TEXT NOT NULL,
  ord          INTEGER NOT NULL,
  text         TEXT NOT NULL,
  locator      TEXT NOT NULL,       -- JSON Locator
  content_hash TEXT NOT NULL,
  created_at   TEXT NOT NULL
);
CREATE INDEX chunks_source ON chunks(source_id, ord);

-- Full-text index over chunk text (external content = no duplicate storage).
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text, content='chunks', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;

-- Fallback vector storage when the sqlite-vec extension cannot be loaded (see store/vectors.py).
CREATE TABLE chunk_vectors (
  chunk_rowid INTEGER PRIMARY KEY,
  vec         BLOB NOT NULL
);

-- Model result cache: key = hash(content hash, model id, prompt version, task). (NFR: cost)
CREATE TABLE model_cache (
  key        TEXT PRIMARY KEY,
  task       TEXT NOT NULL,
  model      TEXT NOT NULL,
  value      TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Resumable, idempotent job queue (no broker to install).
CREATE TABLE jobs (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  payload      TEXT NOT NULL,
  status       TEXT NOT NULL,       -- queued | running | done | failed | cancelled
  priority     INTEGER NOT NULL DEFAULT 0,
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 2,
  dedupe_key   TEXT,
  progress     REAL NOT NULL DEFAULT 0,
  message      TEXT,
  error        TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX jobs_active_dedupe ON jobs(dedupe_key)
  WHERE status IN ('queued', 'running');
CREATE INDEX jobs_pick ON jobs(status, priority DESC, created_at);

-- Chunks whose extraction failed validation twice: shown in the review queue.
CREATE TABLE extraction_issues (
  id         TEXT PRIMARY KEY,
  source_id  TEXT NOT NULL,
  chunk_id   TEXT,
  reason     TEXT NOT NULL,
  raw        TEXT,
  created_at TEXT NOT NULL
);

-- Suggested (never forced) entity merges from entity resolution.
CREATE TABLE merge_suggestions (
  id         TEXT PRIMARY KEY,
  entity_a   TEXT NOT NULL,
  entity_b   TEXT NOT NULL,
  score      REAL NOT NULL,
  reason     TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open',  -- open | dismissed
  created_at TEXT NOT NULL,
  UNIQUE (entity_a, entity_b)
);
