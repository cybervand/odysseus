"""The live-page contract (investigation of 2026-08-06, user directive:
"text from the user should always get committed... leave a running chat and
come back to it live").

What the investigation PROVED (pinned here so it can't silently regress):
  1. Server-side durability is immediate — once a POST lands, the user
     message is a DB row before any streaming begins (SessionManager
     persists per-message; the route builds context BEFORE agent_runs.start).
  2. Runs are detached — they complete and buffer with ZERO subscribers;
     leave-and-return replays the buffer then goes live.
  3. Finished runs evict after a grace period, so replay-on-return has a
     deadline, not permanence.

What the investigation found MISSING (xfail-documented design gaps):
  4. A client-side composer outbox — the only place user text can die is
     the browser-only window before the POST (a session reload bulldozed a
     composed message on 2026-08-06).
  5. A replay/live marker in the resume feed — a replayed run renders
     pixel-identical to live generation; the user watched a recording
     believing the model was processing their (already lost) message.
"""
import asyncio
import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import core.session_manager as csm
import src.agent_runs as ar
from core.models import ChatMessage

_CHAT_ROUTES = pathlib.Path(csm.__file__).resolve().parent.parent / "routes" / "chat_routes.py"
_CHAT_JS = pathlib.Path(csm.__file__).resolve().parent.parent / "static" / "js" / "chat.js"


# ── 1. Durability primitive ──


def _temp_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    cdb.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_persist_message_writes_db_row_immediately(tmp_path, monkeypatch):
    factory = _temp_db(tmp_path)
    monkeypatch.setattr(csm, "SessionLocal", factory)
    db = factory()
    db.add(cdb.Session(id="s1", name="t", endpoint_url="x", model="m"))
    db.commit()
    db.close()

    sm = csm.SessionManager.__new__(csm.SessionManager)
    sm.sessions = {}
    sm._persist_message("s1", ChatMessage("user", "hello durable world"))

    db = factory()
    rows = db.query(cdb.ChatMessage).filter(cdb.ChatMessage.session_id == "s1").all()
    db.close()
    assert len(rows) == 1
    assert rows[0].content == "hello durable world"


def test_add_message_routes_through_persist():
    src = pathlib.Path(csm.__file__).read_text(encoding="utf-8")
    assert "self._persist_message(session_id, message)" in src


def test_route_persists_user_before_starting_run():
    """User-message persistence (inside build_chat_context) must precede the
    detached-run start — durability cannot depend on the stream."""
    src = _CHAT_ROUTES.read_text(encoding="utf-8")
    first_ctx = src.find("ctx = await build_chat_context(")
    run_start = src.find("agent_runs.start(session, _safe_stream())")
    assert first_ctx != -1 and run_start != -1
    assert first_ctx < run_start


# ── 2/3. Detached runs: complete alone, replay on return, evict on a clock ──


@pytest.mark.anyio
async def test_detached_run_completes_and_buffers_without_subscribers():
    async def agen():
        for i in range(3):
            yield f"data: ev{i}\n\n"

    run = ar.start("live-contract-a", agen())
    await run.task
    assert run.status == "done"
    assert len(run.buffer) == 3
    ar._RUNS.pop("live-contract-a", None)


@pytest.mark.anyio
async def test_subscribe_replays_finished_run_buffer():
    async def agen():
        yield "data: one\n\n"
        yield "data: two\n\n"

    run = ar.start("live-contract-b", agen())
    await run.task
    events = [ev async for ev in ar.subscribe("live-contract-b")]
    assert events == ["data: one\n\n", "data: two\n\n"]
    ar._RUNS.pop("live-contract-b", None)


@pytest.mark.anyio
async def test_finished_run_evicted_after_grace(monkeypatch):
    monkeypatch.setattr(ar, "_EVICT_GRACE_S", 0.05)

    async def agen():
        yield "data: x\n\n"

    run = ar.start("live-contract-c", agen())
    await run.task
    assert "live-contract-c" in ar._RUNS
    await asyncio.sleep(0.3)
    assert "live-contract-c" not in ar._RUNS


# ── 4/5. The designed gaps (xfail until built) ──


@pytest.mark.xfail(reason="composer outbox not built yet: user text has no client-side durability before the POST", strict=True)
def test_composer_outbox_exists():
    js = _CHAT_JS.read_text(encoding="utf-8")
    assert "odysseus-draft" in js or "outbox" in js.lower()


@pytest.mark.xfail(reason="replay/live marker not built yet: resumed streams render identically to live generation", strict=True)
def test_resume_feed_marks_replay_boundary():
    src = pathlib.Path(ar.__file__).read_text(encoding="utf-8")
    assert "resume_live_edge" in src
