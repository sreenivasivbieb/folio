-- Changes received during a running job must be processed after that job finishes.
ALTER TABLE jobs ADD COLUMN rerun INTEGER NOT NULL DEFAULT 0;
