-- SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
-- SPDX-License-Identifier: Apache-2.0

CREATE TABLE IF NOT EXISTS graph_sources (
    source_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    root_key TEXT NOT NULL,
    path TEXT NOT NULL,
    module_key TEXT NOT NULL,
    language TEXT,
    status TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    imports_json TEXT NOT NULL,
    entity_count INTEGER NOT NULL,
    relationship_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_modules ON graph_sources(root_key,module_key);
CREATE TABLE IF NOT EXISTS graph_entities (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES graph_sources(source_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    byte_start INTEGER NOT NULL,
    byte_end INTEGER NOT NULL,
    signature TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_entity_source ON graph_entities(source_id,line_start,line_end);
CREATE INDEX IF NOT EXISTS idx_graph_entity_name ON graph_entities(name);
CREATE INDEX IF NOT EXISTS idx_graph_entity_qualified ON graph_entities(qualified_name);
CREATE TABLE IF NOT EXISTS graph_relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES graph_sources(source_id) ON DELETE CASCADE,
    from_id TEXT NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    target_name TEXT NOT NULL,
    target_key TEXT NOT NULL,
    target_leaf TEXT NOT NULL,
    target_mode TEXT NOT NULL,
    target_hint TEXT,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    evidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_relationship_from ON graph_relationships(from_id,kind);
CREATE INDEX IF NOT EXISTS idx_graph_relationship_target ON graph_relationships(target_leaf,kind);
