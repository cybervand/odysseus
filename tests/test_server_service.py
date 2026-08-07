"""Doc 017 — named servers as a service: port allocation, ownership, verbs.

Process-free: launch() is stubbed to seed a fake running job (no subprocess),
the stores live in tmp, and _port_listening defaults to False (every port
free) unless a test says otherwise. The invariants under test are the doc 017
decisions: ports are ASSIGNED not self-reported, conflicts diagnose instead
of report, capability follows the owner, attachment follows the session.
"""
import asyncio
import json
import time
import uuid

import pytest

from src import bg_jobs
from src.agent_tools.bg_job_tools import ManageServerTool


@pytest.fixture
def store(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "bg_jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "bg_jobs.json")
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(bg_jobs, "_SERVERS_FILE", tmp_path / "servers.json")
    monkeypatch.setattr(bg_jobs, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(bg_jobs, "_port_listening", lambda port: False)
    monkeypatch.setattr(bg_jobs, "port_range", lambda: (13000, 13004))
    killed: list = []
    monkeypatch.setattr(bg_jobs, "_kill", lambda pid: killed.append(pid))

    launches: list = []

    def _fake_launch(command, session_id, cwd=None,
                     max_runtime_s=bg_jobs.DEFAULT_MAX_RUNTIME_S, env=None):
        job_id = uuid.uuid4().hex[:12]
        rec = {
            "id": job_id, "session_id": session_id, "command": command,
            "status": "running", "pid": 4321, "started_at": time.time(),
            "ended_at": None, "exit_code": None, "max_runtime_s": max_runtime_s,
            "followed_up": False,
            "log_path": str(jobs_dir / f"{job_id}.log"),
            "exit_path": str(jobs_dir / f"{job_id}.exit"),
        }
        jobs = bg_jobs._load()
        jobs[job_id] = rec
        bg_jobs._save(jobs)
        launches.append({"command": command, "session_id": session_id,
                         "cwd": cwd, "env": env})
        return rec

    monkeypatch.setattr(bg_jobs, "launch", _fake_launch)
    return {"killed": killed, "launches": launches}


def _tool(args, session_id="sess-a", owner="alice"):
    return asyncio.run(ManageServerTool().execute(
        json.dumps(args), {"session_id": session_id, "owner": owner}))


# ── Allocation ──────────────────────────────────────────────────────────────

def test_auto_assign_lowest_free_and_port_env(store):
    st = bg_jobs.server_start("one", "python app.py", "sess-a", owner="alice")
    assert st["port"] == 13000
    assert store["launches"][-1]["env"] == {"PORT": "13000"}


def test_second_server_gets_next_port(store):
    bg_jobs.server_start("one", "python app.py", "sess-a")
    st = bg_jobs.server_start("two", "python app.py", "sess-a")
    assert st["port"] == 13001


def test_restart_keeps_port(store):
    bg_jobs.server_start("one", "python app.py", "sess-a")
    bg_jobs.server_start("two", "python app.py", "sess-a")
    st = bg_jobs.server_restart("one")
    assert st["port"] == 13000


def test_out_of_range_request_teaches(store):
    with pytest.raises(bg_jobs.PortAllocationError) as e:
        bg_jobs.server_start("one", "python app.py", "sess-a", port=8090)
    assert "outside" in str(e.value)
    assert "PORT env var" in str(e.value)


def test_conflict_names_the_owning_server(store):
    bg_jobs.server_start("one", "python app.py", "sess-a")
    with pytest.raises(bg_jobs.PortAllocationError) as e:
        bg_jobs.server_start("two", "python app.py", "sess-a", port=13000)
    assert "'one'" in str(e.value)
    assert "estart" in str(e.value)  # restart guidance, not a bare refusal


def test_busy_unregistered_port_diagnosed(store, monkeypatch):
    monkeypatch.setattr(bg_jobs, "_port_listening", lambda port: port == 13002)
    with pytest.raises(bg_jobs.PortAllocationError) as e:
        bg_jobs.server_start("one", "python app.py", "sess-a", port=13002)
    assert "busy" in str(e.value)


def test_auto_assign_skips_listening_ports(store, monkeypatch):
    monkeypatch.setattr(bg_jobs, "_port_listening", lambda port: port == 13000)
    st = bg_jobs.server_start("one", "python app.py", "sess-a")
    assert st["port"] == 13001


def test_exhaustion_teaches_cleanup(store):
    for i in range(5):  # fills 13000-13004
        bg_jobs.server_start(f"s{i}", "python app.py", "sess-a")
    with pytest.raises(bg_jobs.PortAllocationError) as e:
        bg_jobs.server_start("overflow", "python app.py", "sess-a")
    assert "remove" in str(e.value)


def test_grandfathered_out_of_range_port_survives_restart(store):
    # skilodge case: entry predates the range with port 8090 — restarts must
    # not suddenly refuse it.
    bg_jobs.server_start("legacy", "python app.py", "sess-a")
    servers = bg_jobs._load_servers()
    servers["legacy"]["port"] = 8090
    bg_jobs._save_servers(servers)
    st = bg_jobs.server_restart("legacy")
    assert st["port"] == 8090


# ── Ownership + attachment ──────────────────────────────────────────────────

def test_owner_and_autostart_sticky_across_restart(store):
    bg_jobs.server_start("one", "python app.py", "sess-a",
                         owner="alice", autostart=True)
    st = bg_jobs.server_restart("one")
    assert st["owner"] == "alice"
    assert st["autostart"] is True


def test_other_users_servers_are_invisible(store):
    bg_jobs.server_start("hers", "python app.py", "sess-b", owner="beth")
    out = _tool({"action": "status", "name": "hers"}, owner="alice")
    assert "unknown server" in out["error"]
    listed = _tool({"action": "list"}, owner="alice")
    assert "hers" not in listed["output"]


def test_legacy_ownerless_entries_stay_reachable(store):
    bg_jobs.server_start("legacy", "python app.py", "sess-b", owner=None)
    out = _tool({"action": "status", "name": "legacy"}, owner="alice")
    assert "error" not in out


def test_session_attachment_grants_access_despite_owner_gap(store):
    # Regression (2026-08-07): the registry dispatch dropped ctx owner, and
    # the tool told the chat its OWN server was unknown. Session attachment
    # must be an independent grant.
    bg_jobs.server_start("mine", "python app.py", "sess-a", owner="admin")
    out = _tool({"action": "status", "name": "mine"}, session_id="sess-a", owner=None)
    assert "error" not in out
    assert "mine" in out["output"]


def test_adopt_moves_attachment_not_capability(store):
    bg_jobs.server_start("mine", "python app.py", "sess-old", owner="alice")
    out = _tool({"action": "adopt", "name": "mine"},
                session_id="sess-new", owner="alice")
    assert "attached to this chat" in out["output"]
    assert bg_jobs.server_status("mine")["session_id"] == "sess-new"


def test_remove_deletes_entry(store):
    bg_jobs.server_start("gone", "python app.py", "sess-a", owner="alice")
    _tool({"action": "remove", "name": "gone"})
    assert bg_jobs.server_status("gone") is None


# ── Query guardrails (process-free: only the refusals) ──────────────────────

def test_query_path_must_be_rooted(store):
    bg_jobs.server_start("one", "python app.py", "sess-a", owner="alice")
    out = _tool({"action": "query", "name": "one", "path": "http://evil.example/x"})
    assert "must start with '/'" in out["error"]


def test_query_method_allowlist(store):
    bg_jobs.server_start("one", "python app.py", "sess-a", owner="alice")
    out = _tool({"action": "query", "name": "one", "method": "DELETE"})
    assert "GET and POST" in out["error"]


# ── Autostart reconciler ────────────────────────────────────────────────────

def test_reconcile_revives_flagged_dead_servers(store):
    bg_jobs.server_start("auto", "python app.py", "sess-a",
                         owner="alice", autostart=True)
    bg_jobs.server_start("manual", "python app.py", "sess-a", owner="alice")
    # Both die.
    jobs = bg_jobs._load()
    for rec in jobs.values():
        rec["status"] = "failed"
    bg_jobs._save(jobs)
    revived = bg_jobs.reconcile_autostart()
    assert revived == ["auto"]
    st = bg_jobs.server_status("auto")
    assert st["running"] is True
    # Attachment restored to the chat; the JOB was launched as system.
    assert st["session_id"] == "sess-a"
    assert store["launches"][-1]["session_id"] == bg_jobs.SYSTEM_OWNER


def test_reconcile_skips_deliberately_stopped(store):
    bg_jobs.server_start("auto", "python app.py", "sess-a", autostart=True)
    bg_jobs.server_stop("auto")
    assert bg_jobs.reconcile_autostart() == []


# ── Agent-loop manifest (doc 017 §3) ────────────────────────────────────────

def test_manifest_builds_with_public_host(store, monkeypatch):
    # Regression: the manifest's os.environ read NameError'd EVERY agent run
    # once servers existed (agent_loop had no `import os`; 2026-08-07, hit
    # production because no test registered servers and built the manifest).
    from src.agent_loop import _named_server_context_message
    monkeypatch.setenv("ODYSSEUS_PUBLIC_HOST", "192.168.1.192")
    bg_jobs.server_start("mine", "python app.py", "sess-a", owner="alice")
    servers = bg_jobs.server_list()
    msg = _named_server_context_message(servers, [])
    text = msg["content"]
    assert "url=http://192.168.1.192:13000" in text
    assert "localhost is wrong" in text


def test_manifest_two_sections_and_adopt_hint(store, monkeypatch):
    monkeypatch.delenv("ODYSSEUS_PUBLIC_HOST", raising=False)
    from src.agent_loop import _named_server_context_message
    bg_jobs.server_start("here", "python app.py", "sess-a")
    bg_jobs.server_start("there", "python app.py", "sess-b")
    servers = {s["name"]: s for s in bg_jobs.server_list()}
    msg = _named_server_context_message([servers["here"]], [servers["there"]])
    text = msg["content"]
    assert "THIS chat" in text
    assert "OTHER chats" in text
    assert "adopt" in text
