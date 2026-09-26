-- SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
-- SPDX-License-Identifier: Apache-2.0

CREATE TABLE IF NOT EXISTS kc_cards (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL UNIQUE REFERENCES sources(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    subcategory TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    positive_text TEXT,
    negative_text TEXT,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    raw_yaml TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kc_category ON kc_cards(category);
CREATE INDEX IF NOT EXISTS idx_kc_confidence ON kc_cards(confidence);
CREATE VIRTUAL TABLE IF NOT EXISTS kc_fts USING fts5(
    card_id UNINDEXED, title, category, subcategory, description,
    positive_text, negative_text, method_texts, inputs, outputs, codes,
    tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS kc_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES kc_cards(id) ON DELETE CASCADE,
    field_type TEXT NOT NULL CHECK(field_type IN ('description','positive','negative','code')),
    embedding BLOB NOT NULL,
    UNIQUE(card_id, field_type)
);
CREATE INDEX IF NOT EXISTS idx_kc_embed_card_field ON kc_embeddings(card_id, field_type);
CREATE TRIGGER IF NOT EXISTS kc_delete_fts AFTER DELETE ON kc_cards
BEGIN
    DELETE FROM kc_fts WHERE card_id=OLD.id;
END;
