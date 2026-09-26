# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import finish

from ragdbman import db
from ragdbman.engine import PROGRESS
from ragdbman.web import create_app

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def job_row(status="running", **progress):
    return dict(
        status=status,
        params_json="{}",
        progress_json=json.dumps(
            {
                **PROGRESS,
                "phase": "indexing",
                "processing_started_at": (NOW - timedelta(seconds=20)).isoformat(),
                **progress,
            }
        ),
        started_at=(NOW - timedelta(seconds=30)).isoformat(),
        updated_at=NOW.isoformat(),
        finished_at=None,
    )


def test_total_percent_elapsed_and_remaining_formula():
    result = db.decode_job(job_row(total=10, completed=1, skipped=1, failed=1, unchanged=1), NOW)
    assert result["progress"]["processed"] == 4
    assert result["progress"]["percent"] == 40
    assert result["timing"]["elapsed_seconds"] == 30
    assert result["timing"]["estimated_remaining_seconds"] == 30  # 20 / 4 * 6


@pytest.mark.parametrize("phase,total", [("discovering", None), ("indexing", 10), ("pruning", 0)])
def test_no_made_up_eta_before_samples_or_during_cleanup(phase, total):
    result = db.decode_job(job_row(phase=phase, total=total), NOW)
    assert result["timing"]["estimated_remaining_seconds"] is None


@pytest.mark.parametrize("status", ["cancelled", "paused", "failed"])
def test_terminal_elapsed_freezes_without_false_completion(status):
    row = job_row(status, total=10, completed=3)
    row["finished_at"] = NOW.isoformat()
    result = db.decode_job(row, NOW + timedelta(days=5))
    assert result["timing"]["elapsed_seconds"] == 30
    assert result["timing"]["estimated_remaining_seconds"] is None
    assert result["progress"]["percent"] == 30
    assert result["progress"]["phase"] == status


def test_empty_completed_scan_is_complete():
    result = db.decode_job(job_row("completed", total=0), NOW)
    assert result["progress"]["percent"] == 100
    assert result["timing"]["estimated_remaining_seconds"] == 0


def test_missing_total_and_timing_are_safe():
    row = job_row()
    row["started_at"] = None
    row["progress_json"] = '{"completed": 4, "skipped": 1}'
    result = db.decode_job(row, NOW)
    assert result["progress"]["percent"] is None
    assert result["timing"]["elapsed_seconds"] == 0
    assert result["timing"]["estimated_remaining_seconds"] is None


async def test_total_visible_while_first_file_is_still_embedding(engine, fake, source_dir):
    await engine.create_collection(name="progress")
    for name in ("a.txt", "b.txt", "c.bin"):
        (source_dir / name).write_text("Indexing progress is visible.")
    fake.entered.clear()
    fake.gate = asyncio.Event()
    started = engine.start_scan("progress", str(source_dir))
    assert started["progress"]["total"] is None
    await asyncio.wait_for(fake.entered.wait(), 3)
    try:
        app = create_app(engine, False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as c:
            response = await asyncio.wait_for(c.get(f"/api/collections/progress/jobs/{started['id']}"), 1)
        result = response.json()
        assert result["progress"]["total"] == result["progress"]["discovered"] == 3
        assert result["progress"]["processed"] == 0
        assert result["progress"]["percent"] == 0
        assert result["timing"]["elapsed_seconds"] >= 0
        assert result["timing"]["estimated_remaining_seconds"] is None
    finally:
        fake.gate.set()
    final = await finish(engine, "progress", started)
    assert final["progress"]["processed"] == 3
    assert final["progress"]["completed"] == 2
    assert final["progress"]["skipped"] == 1
    assert final["progress"]["percent"] == 100
    assert final["progress"]["phase"] == "finished"
    assert final["timing"]["estimated_remaining_seconds"] == 0
    # The completed record must not keep accumulating elapsed wall time.
    assert engine.get_job("progress", started["id"])["timing"] == final["timing"]
    again = await finish(engine, "progress", engine.start_scan("progress", str(source_dir)))
    assert again["progress"]["unchanged"] == 2
    assert again["progress"]["processed"] == again["progress"]["total"] == 3


async def test_empty_scan_and_rebuild_totals(engine, source_dir):
    await engine.create_collection(name="empty")
    empty = await finish(engine, "empty", engine.start_scan("empty", str(source_dir)))
    assert empty["progress"]["total"] == 0 and empty["progress"]["percent"] == 100
    (source_dir / "one.txt").write_text("One tracked source.")
    await engine.add_file("empty", str(source_dir / "one.txt"))
    rebuild = await finish(engine, "empty", engine.rebuild_collection("empty", confirm=True))
    assert rebuild["progress"]["total"] == rebuild["progress"]["processed"] == 1


async def test_cancel_and_resume_reset_attempt_statistics(engine, fake, source_dir):
    await engine.create_collection(name="cancel")
    for n in range(3):
        (source_dir / f"{n}.txt").write_text(f"Source {n}")
    fake.entered.clear()
    fake.gate = asyncio.Event()
    started = engine.start_scan("cancel", str(source_dir))
    await asyncio.wait_for(fake.entered.wait(), 3)
    engine.cancel_job(started["id"])
    fake.gate.set()
    cancelled = await finish(engine, "cancel", started)
    assert cancelled["progress"]["total"] == 3
    assert cancelled["progress"]["percent"] < 100
    assert cancelled["timing"]["estimated_remaining_seconds"] is None
    resumed = engine.resume_job("cancel", started["id"])
    assert resumed["progress"]["total"] is None
    assert resumed["timing"]["elapsed_seconds"] == 0
    final = await finish(engine, "cancel", resumed)
    assert final["started_at"] >= cancelled["finished_at"]
    assert final["progress"]["percent"] == 100
    assert final["progress"]["processed"] == 3


async def test_recovery_does_not_count_daemon_downtime(engine):
    await engine.create_collection(name="recover")
    identifier = db.uid()
    old = (NOW - timedelta(days=2)).isoformat()
    last = (NOW - timedelta(days=2, seconds=-20)).isoformat()
    with engine.connection("recover") as conn:
        db.insert(
            conn,
            "jobs",
            dict(
                id=identifier,
                collection_id=engine.get_collection("recover")["id"],
                kind="scan",
                status="running",
                params_json="{}",
                progress_json=json.dumps(PROGRESS),
                created_at=old,
                updated_at=last,
                started_at=old,
            ),
        )
    engine.recover()
    result = engine.get_job("recover", identifier)
    assert result["status"] == "paused"
    assert result["timing"]["elapsed_seconds"] == 20
