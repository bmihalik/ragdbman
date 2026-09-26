-- SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
-- SPDX-License-Identifier: Apache-2.0

-- Per-collection SQLite schema. Everything except the vec0 virtual table
-- (created dynamically once the collection's embedding dimension is known
-- in db.ensure_vectors) lives here.

CREATE TABLE IF NOT EXISTS collection_meta (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    description             TEXT,
    managed_root            TEXT NOT NULL,
    kind                    TEXT NOT NULL DEFAULT 'general', -- general | source_code | knowledge_cards
    embedding_provider      TEXT NOT NULL,
    embedding_model         TEXT NOT NULL,
    embedding_dimensions    INTEGER,
    embedding_keep_alive    TEXT NOT NULL,
    tokenizer               TEXT NOT NULL,
    tokenizer_mode          TEXT NOT NULL,
    chunk_size_tokens       INTEGER NOT NULL,
    chunk_overlap_tokens    INTEGER NOT NULL,
    config_json             TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_roots (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    recursive   INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id                      TEXT PRIMARY KEY,
    root_id                 TEXT REFERENCES source_roots(id),
    origin_type             TEXT NOT NULL,
    original_path           TEXT,
    canonical_path          TEXT,
    original_filename       TEXT NOT NULL,
    managed_relative_path   TEXT,
    source_url              TEXT,
    markdown_path           TEXT,
    mime_type               TEXT,
    extension               TEXT,
    size_bytes              INTEGER,
    modified_at             TEXT,
    discovered_at           TEXT NOT NULL,
    content_hash_sha256     TEXT,
    extraction_hash         TEXT,
    status                  TEXT NOT NULL,
    status_detail           TEXT,
    page_count              INTEGER,
    duration_seconds        REAL,
    language                TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    indexed_at              TEXT,
    deleted_at              TEXT
);

CREATE INDEX IF NOT EXISTS idx_sources_canonical_path ON sources(canonical_path);
CREATE INDEX IF NOT EXISTS idx_sources_content_hash ON sources(content_hash_sha256);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);

CREATE TABLE IF NOT EXISTS source_versions (
    id                      TEXT PRIMARY KEY,
    source_id               TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    content_hash_sha256     TEXT NOT NULL,
    indexed_at              TEXT,
    note                    TEXT,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id                  TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    kind                TEXT NOT NULL, -- extracted_text | ocr | transcript | thumbnail | normalized
    text_content        TEXT,
    path                TEXT,
    extractor_name       TEXT,
    extractor_version    TEXT,
    command_fingerprint  TEXT,
    created_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_source ON artifacts(source_id);

CREATE TABLE IF NOT EXISTS chunks (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    id                   TEXT UNIQUE NOT NULL,
    source_id            TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    artifact_id          TEXT REFERENCES artifacts(id),
    chunk_index          INTEGER NOT NULL,
    text                 TEXT NOT NULL,
    normalized_text      TEXT NOT NULL,
    char_start           INTEGER NOT NULL,
    char_end             INTEGER NOT NULL,
    percent_position     REAL,
    token_start          INTEGER NOT NULL,
    token_end            INTEGER NOT NULL,
    token_count          INTEGER NOT NULL,
    page_start           INTEGER,
    page_end             INTEGER,
    slide_start          INTEGER,
    slide_end            INTEGER,
    time_start_ms        INTEGER,
    time_end_ms          INTEGER,
    line_start           INTEGER,
    line_end             INTEGER,
    section_path         TEXT,
    heading              TEXT,
    language             TEXT,
    embedding_model      TEXT NOT NULL,
    embedding_version    INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id    TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL UNIQUE,
    dims        INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    heading,
    section_path,
    filename
);

CREATE TABLE IF NOT EXISTS metadata_fields (
    id              TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    value_type      TEXT NOT NULL, -- number | date | currency | percentage | text
    unit_family     TEXT,
    aliases_json    TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    is_system_field INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunk_numeric_values (
    id                    TEXT PRIMARY KEY,
    chunk_id              TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    source_id             TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    field_id              TEXT NOT NULL REFERENCES metadata_fields(id),
    raw_value             TEXT NOT NULL,
    normalized_number     REAL,
    normalized_date_utc   TEXT,
    currency_code         TEXT,
    unit                  TEXT,
    confidence            REAL NOT NULL,
    char_start            INTEGER,
    char_end              INTEGER
);

CREATE INDEX IF NOT EXISTS idx_numeric_field_value ON chunk_numeric_values(field_id, normalized_number);
CREATE INDEX IF NOT EXISTS idx_numeric_field_date ON chunk_numeric_values(field_id, normalized_date_utc);

CREATE TABLE IF NOT EXISTS keywords (
    id              TEXT PRIMARY KEY,
    canonical_form  TEXT NOT NULL UNIQUE,
    display_form    TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'term', -- term | entity | field_alias
    doc_frequency   INTEGER NOT NULL DEFAULT 0,
    chunk_frequency INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunk_keywords (
    chunk_id            TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    keyword_id          TEXT NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    confidence          REAL NOT NULL DEFAULT 1.0,
    extraction_source   TEXT NOT NULL DEFAULT 'deterministic',
    PRIMARY KEY (chunk_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    collection_id   TEXT NOT NULL,
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL,
    params_json     TEXT NOT NULL DEFAULT '{}',
    progress_json   TEXT NOT NULL DEFAULT '{}',
    current_item    TEXT,
    error_summary   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_items (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_path     TEXT,
    source_id       TEXT,
    classification  TEXT,
    stage           TEXT NOT NULL,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_job_items_stage ON job_items(stage);

CREATE TABLE IF NOT EXISTS errors (
    id          TEXT PRIMARY KEY,
    job_id      TEXT,
    source_id   TEXT,
    error_code  TEXT NOT NULL,
    message     TEXT NOT NULL,
    detail_json TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             TEXT PRIMARY KEY,
    actor          TEXT NOT NULL,
    action         TEXT NOT NULL,
    collection_id  TEXT,
    source_id      TEXT,
    job_id         TEXT,
    detail_json    TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
