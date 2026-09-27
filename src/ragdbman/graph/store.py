# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Separate graph database with a primary-database transactional outbox."""

import json
from importlib.resources import files

from .. import db
from ..connections import CollectionDatabase


def initialize_primary(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS source_graph_outbox (
        source_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
        content_hash TEXT, payload_json TEXT, created_at TEXT NOT NULL
    )""")


def has_outbox(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='source_graph_outbox'").fetchone() is not None


def queue(conn, source_id, snapshot=None):
    """Called only inside the same transaction as its source/chunk mutation."""
    conn.execute(
        """INSERT OR REPLACE INTO source_graph_outbox
        (source_id,event_id,content_hash,payload_json,created_at) VALUES (?,?,?,?,?)""",
        (
            source_id,
            db.uid(),
            snapshot["content_hash"] if snapshot else None,
            json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else None,
            db.now(),
        ),
    )


class GraphStore:
    def __init__(self, path):
        self.path = path
        self.pool = CollectionDatabase(path)

    def initialize(self):
        with self.pool.connection() as conn:
            conn.executescript(files(__package__).joinpath("schema.sql").read_text(encoding="utf-8"))

    def status(self):
        if not self.path.is_file():
            return dict(available=False, sources=0, entities=0, relationships=0, statuses={})
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*),COALESCE(SUM(entity_count),0),COALESCE(SUM(relationship_count),0) FROM graph_sources"
            ).fetchone()
            return dict(
                available=True,
                sources=row[0],
                entities=row[1],
                relationships=row[2],
                statuses=dict(conn.execute("SELECT status,COUNT(*) FROM graph_sources GROUP BY status")),
            )

    def is_current(self, source_id, digest, revision, root_key, path):
        if not self.path.is_file():
            return False
        with self.pool.connection() as conn:
            row = conn.execute("SELECT * FROM graph_sources WHERE source_id=?", (source_id,)).fetchone()
            return bool(
                row
                and row["content_hash"] == digest
                and row["parser_version"] == revision
                and row["root_key"] == root_key
                and row["path"] == path
            )

    def apply(self, event):
        with self.pool.connection() as conn, db.transaction(conn):
            previous = conn.execute(
                "SELECT event_id FROM graph_sources WHERE source_id=?", (event["source_id"],)
            ).fetchone()
            if previous and previous[0] == event["event_id"]:
                return  # Retry after graph commit but before primary outbox acknowledgement.
            conn.execute("DELETE FROM graph_sources WHERE source_id=?", (event["source_id"],))
            if event["payload_json"] is None:
                return
            payload = json.loads(event["payload_json"])
            db.insert(
                conn,
                "graph_sources",
                dict(
                    source_id=event["source_id"],
                    event_id=event["event_id"],
                    **{
                        k: payload[k]
                        for k in (
                            "content_hash",
                            "parser_version",
                            "root_key",
                            "path",
                            "module_key",
                            "language",
                            "status",
                        )
                    },
                    warnings_json=json.dumps(payload["warnings"]),
                    imports_json=json.dumps(payload["imports"]),
                    entity_count=len(payload["entities"]),
                    relationship_count=len(payload["relationships"]),
                ),
            )
            for entity in payload["entities"]:
                db.insert(conn, "graph_entities", {**entity, "source_id": event["source_id"]})
            for edge in payload["relationships"]:
                db.insert(conn, "graph_relationships", {**edge, "source_id": event["source_id"]})

    def flush(self, primary):
        if not has_outbox(primary):
            return 0
        if not primary.execute("SELECT 1 FROM source_graph_outbox LIMIT 1").fetchone():
            return 0
        self.initialize()
        applied = 0
        while True:
            events = db.rows(
                primary, "SELECT * FROM source_graph_outbox ORDER BY created_at,source_id LIMIT 64"
            )
            if not events:
                break
            for event in events:
                source = primary.execute(
                    "SELECT status,content_hash_sha256 FROM sources WHERE id=?", (event["source_id"],)
                ).fetchone()
                if event["payload_json"] is not None and (
                    source is None
                    or source["status"] != "indexed"
                    or source["content_hash_sha256"] != event["content_hash"]
                ):
                    # Stale/replayed work must not resurrect deleted or changed source data.
                    event["payload_json"] = None
                self.apply(event)
                primary.execute(
                    "DELETE FROM source_graph_outbox WHERE source_id=? AND event_id=?",
                    (event["source_id"], event["event_id"]),
                )
                applied += 1
        return applied

    def close(self):
        self.pool.close()
