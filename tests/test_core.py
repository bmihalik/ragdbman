# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest
import tomli_w
from pydantic import ValidationError

from ragdbman import db
from ragdbman.cli import init_config, main
from ragdbman.config import GlobalConfig
from ragdbman.errors import RagError, require_confirmation
from ragdbman.models import CreateCollection, NumericFilter
from ragdbman.scanner import classify, discover, sha256_file


def test_defaults():
    c = GlobalConfig()
    assert c.server.port == 8765
    assert c.ollama.embedding_model == "bge-m3:567m"
    assert c.source_code.chunk_size_tokens == 400
    assert c.defaults.chunk_overlap_tokens == 64
    assert c.media.scratch_dir is None
    assert c.storage.markdown_sidecar_enabled


@pytest.mark.parametrize(
    "data",
    [
        {"defaults": {"chunk_size_tokens": 3, "chunk_overlap_tokens": 3}},
        {"source_code": {"chunk_size_tokens": 10, "chunk_overlap_tokens": 11}},
        {"server": {"allow_remote_bind": True}},
        {"server": {"bind": "0.0.0.0"}},
        {"search": {"default_top_k": 100}},
        {"logging": {"level": "verbose"}},
        {"storage": {"markdown_sidecar_dir_name": "../escape"}},
        {"storage": {"markdown_sidecar_dir_name": "."}},
        {"server": {"mcp_path": "/"}},
        {"ollama": {"embedding_batch_size": 0}},
        {"unknown_section": {}},
    ],
)
def test_invalid_config(data):
    with pytest.raises(ValidationError):
        GlobalConfig.model_validate(data)


@pytest.mark.parametrize("level", ["error", "warn", "info", "debug", "trace"])
def test_log_levels(level):
    assert GlobalConfig(logging={"level": level}).logging.level == level


def test_toml_roundtrip(cfg, tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(tomli_w.dumps(cfg.model_dump(exclude_none=True)))
    assert GlobalConfig.load(p) == cfg
    assert GlobalConfig.load(tmp_path / "absent.toml") == GlobalConfig()


def test_bad_toml(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[broken")
    with pytest.raises(RagError, match="CONFIG_INVALID"):
        GlobalConfig.load(p)


def test_init_refuses_overwrite(tmp_path):
    p = tmp_path / "config.toml"
    init_config(p)
    original = p.read_text()
    assert "# mineru_command" in original
    assert GlobalConfig.load(p).media.mineru_command is None
    with pytest.raises(RagError):
        init_config(p)
    assert p.read_text() == original


def test_cli_init(tmp_path):
    p = tmp_path / "c.toml"
    main(["init", "--config", str(p)])
    assert p.exists()


@pytest.mark.parametrize("name", ["../escape", "", "/abs", "a/b", "a b", ".", "a" * 129])
def test_collection_name_validation(name):
    with pytest.raises(ValidationError):
        CreateCollection(name=name)


@pytest.mark.parametrize("op", ["equal", "between"])
def test_numeric_filter_missing_operands(op):
    with pytest.raises(ValidationError):
        NumericFilter(field="price", op=op)


def test_error_and_confirmation():
    e = RagError("SOURCE_NOT_FOUND", "missing", {"id": 1})
    assert e.status_code == 404
    assert e.as_dict()["context"] == {"id": 1}
    with pytest.raises(RagError, match="CONFIRMATION_REQUIRED"):
        require_confirmation(False)
    require_confirmation(True)


def test_path_allowlist(cfg, source_dir, tmp_path):
    p = source_dir / "a"
    p.write_text("x")
    assert cfg.checked_path(p) == p
    with pytest.raises(RagError):
        cfg.checked_path(tmp_path / "sources-evil" / "a")
    target = tmp_path / "secret"
    target.write_text("secret")
    (source_dir / "escape").symlink_to(target)
    with pytest.raises(RagError):
        cfg.checked_path(source_dir / "escape")


@pytest.mark.parametrize("hidden", [False, True])
def test_scanner_excludes_sidecars(cfg, source_dir, hidden):
    cfg.defaults.index_hidden_files = hidden
    (source_dir / "visible.txt").write_text("hello")
    (source_dir / ".hidden.txt").write_text("hidden")
    sidecar = source_dir / ".ragdbman"
    sidecar.mkdir()
    (sidecar / "copy.md").write_text("copy")
    names = [p.name for p in discover(source_dir, cfg)]
    assert "copy.md" not in names
    assert (".hidden.txt" in names) == hidden


def test_nonrecursive_and_symlink_loop(cfg, source_dir):
    (source_dir / "dir").mkdir()
    (source_dir / "dir" / "child.txt").write_text("x")
    (source_dir / "root.txt").write_text("x")
    (source_dir / "dir" / "loop").symlink_to(source_dir, target_is_directory=True)
    assert len(list(discover(source_dir, cfg, False))) == 1
    cfg.defaults.follow_symlinks = True
    assert len(list(discover(source_dir, cfg))) == 2


def test_hash_classification(source_dir):
    p = source_dir / "a.txt"
    p.write_text("stable")
    digest = sha256_file(p)
    assert digest == sha256_file(p)
    assert classify(None, digest, True) == "new"
    assert classify(None, digest, False) == "unsupported"
    assert classify({"status": "indexed", "content_hash_sha256": digest}, digest, True) == "unchanged"
    assert classify({"status": "failed", "content_hash_sha256": digest}, digest, True) == "previously_failed"
    assert classify({"status": "indexed", "content_hash_sha256": "other"}, digest, True) == "changed"


def test_database_initialization_and_vectors(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = db.connect(path)
    db.initialize_schema(conn)
    fields = db.rows(conn, "SELECT * FROM metadata_fields ORDER BY canonical_name")
    db.initialize_schema(conn)
    assert db.rows(conn, "SELECT * FROM metadata_fields ORDER BY canonical_name") == fields
    assert len(fields) == len(db.SYSTEM_FIELDS)
    assert "markdown_path" in {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
    db.ensure_vectors(conn, 4)
    db.ensure_vectors(conn, 4)
    with pytest.raises(RagError, match="VECTOR_SCHEMA_MISMATCH"):
        db.ensure_vectors(conn, 8)
    import sqlite_vec

    for i, v in enumerate([[1, 0, 0, 0], [0, 1, 0, 0], [0.9, 0.1, 0, 0]], 1):
        conn.execute(
            "INSERT INTO chunks_vec0(rowid,embedding) VALUES (?,?)", (i, sqlite_vec.serialize_float32(v))
        )
    query = sqlite_vec.serialize_float32([1, 0, 0, 0])
    assert (
        conn.execute(
            "SELECT rowid FROM chunks_vec0 WHERE embedding MATCH ? AND k=2 ORDER BY distance", (query,)
        ).fetchone()[0]
        == 1
    )
    conn.execute("DELETE FROM chunks_vec0 WHERE rowid=1")
    assert (
        conn.execute(
            "SELECT rowid FROM chunks_vec0 WHERE embedding MATCH ? AND k=2 ORDER BY distance", (query,)
        ).fetchone()[0]
        == 3
    )
    conn.close()


def test_transaction_rollback():
    conn = db.connect(":memory:")
    conn.execute("CREATE TABLE example(value)")
    with pytest.raises(ValueError), db.transaction(conn):
        conn.execute("INSERT INTO example VALUES (1)")
        raise ValueError()
    assert conn.execute("SELECT count(*) FROM example").fetchone()[0] == 0
    conn.close()


async def test_registry_repair_from_db(engine, cfg):
    collection = await engine.create_collection(name="restore")
    Path(cfg.storage.registry_path).write_text("{corrupt")
    result = engine.repair_registry()
    assert result[0]["id"] == collection["id"]
    assert json.loads(Path(cfg.storage.registry_path).read_text())["schema_version"] == 1
