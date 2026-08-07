"""manage_server + the foreground server guard (the stale-process lesson).

2026-08-06: a model fixed a bug on disk while the old Flask process kept
serving it — restarting had no sanctioned verb and was forbidden by the
brief. Now servers are named, detached, unreaped jobs with start / stop /
restart / status / logs; foreground bash REFUSES known never-returning
commands and points here; `cd X && #!bg` (the observed marker misuse) is
honored as background intent.
"""
import asyncio
import json

import src.bg_jobs as bj
from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS
from src.agent_tools.bg_job_tools import ManageServerTool
from src.agent_tools.subprocess_tools import _server_command_guard
from src.tool_execution import _split_bg_marker
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def test_registered_everywhere():
    assert "manage_server" in TOOL_HANDLERS
    assert "manage_server" in TOOL_TAGS
    names = [(s.get("function") or {}).get("name") for s in FUNCTION_TOOL_SCHEMAS]
    assert "manage_server" in names


# ── The guard ──


def test_guard_blocks_known_server_commands():
    for cmd in (
        "cd /app/data/skilodge && python app.py",
        "npm run dev",
        "vite preview --open",
        "cd site && flask run",
        "python3 -m http.server 8000",
    ):
        g = _server_command_guard(cmd)
        assert g is not None, cmd
        assert "manage_server" in g["error"]
        assert "restart" in g["error"]          # teaches the stale-process lesson


def test_guard_allows_normal_commands():
    for cmd in ("npm run build", "python script.py", "ls -la", "npm install", "python -m pytest"):
        assert _server_command_guard(cmd) is None, cmd


def test_fg_override_allows_finite_scripts():
    assert _server_command_guard("#!fg\npython app.py") is None


def test_bg_marker_mid_line_tolerated():
    # The observed qwen shape: marker after && is a shell comment — honor
    # the intent as background instead of running foreground.
    is_bg, cmd = _split_bg_marker("cd /app/data/skilodge && #!bg\npython app.py")
    assert is_bg is True
    assert "cd /app/data/skilodge" in cmd and "python app.py" in cmd
    assert "#!bg" not in cmd


def test_bg_marker_first_line_still_works():
    is_bg, cmd = _split_bg_marker("#!bg\nnpm install")
    assert is_bg is True and cmd == "npm install"


# ── The tool (bg_jobs faked; no real processes) ──


def _fake_bg(monkeypatch, tmp_path):
    servers_file = tmp_path / "servers.json"
    monkeypatch.setattr(bj, "_SERVERS_FILE", servers_file)
    launched = []
    port_envs = []
    listening = set()

    def fake_launch(command, session_id, cwd=None, max_runtime_s=0, env=None):
        launched.append(command)
        port_envs.append((env or {}).get("PORT"))
        return {"id": f"job{len(launched)}", "started_at": 1750000000.0}

    fake_jobs = {}

    def fake_get(job_id):
        return fake_jobs.get(job_id, {"status": "running", "exit_code": None, "output": "serving on 8090"})

    monkeypatch.setattr(bj, "launch", fake_launch)
    monkeypatch.setattr(bj, "get", fake_get)
    monkeypatch.setattr(bj, "kill", lambda job_id: fake_jobs.setdefault(job_id, {}).update(status="failed") or fake_jobs[job_id])
    monkeypatch.setattr(bj, "_port_listening", lambda port: port in listening)
    return launched, port_envs, listening


def _run(tool, payload):
    return asyncio.run(tool.execute(json.dumps(payload), {"session_id": "sess1"}))


def test_start_status_restart_stop_cycle(monkeypatch, tmp_path):
    launched, port_envs, listening = _fake_bg(monkeypatch, tmp_path)
    tool = ManageServerTool()

    # Doc 017 contract: no port in the call — one is ASSIGNED from the
    # reserved range and exported to the process as PORT.
    r = _run(tool, {"action": "start", "name": "lodge", "command": "python app.py",
                    "cwd": "/app/data/skilodge"})
    assert r["exit_code"] == 0 and "RUNNING" in r["output"]
    assert port_envs[0] == "13000"

    listening.add(13000)   # the app came up on its assigned port
    r = _run(tool, {"action": "status", "name": "lodge"})
    assert "port 13000 listening" in r["output"]

    r = _run(tool, {"action": "restart", "name": "lodge"})
    assert "code edits are now live" in r["output"]
    assert len(launched) == 2                 # restart relaunched same spec
    assert launched[0] == launched[1] == "python app.py"
    assert port_envs[1] == "13000"            # restart keeps the assigned port

    r = _run(tool, {"action": "logs", "name": "lodge"})
    assert "serving on 8090" in r["output"]

    r = _run(tool, {"action": "stop", "name": "lodge"})
    assert r["exit_code"] == 0


def test_fresh_start_with_out_of_range_port_teaches(monkeypatch, tmp_path):
    # Doc 017: models must not pick ports; a fresh start naming one outside
    # the range is refused with the PORT-env teaching, not honored.
    _fake_bg(monkeypatch, tmp_path)
    r = _run(ManageServerTool(), {"action": "start", "name": "lodge",
                                  "command": "python app.py", "port": 8091})
    assert r["exit_code"] == 1
    assert "PORT env var" in r["error"]


def test_pid_alive_eperm_means_alive(monkeypatch):
    # EPERM proves the process exists (owned by another uid). Misreading it
    # as dead made the poller reap a live server 1.2s after launch.
    import os as _os
    from core import platform_compat as pc
    if pc.IS_WINDOWS:
        return  # POSIX-only branch

    def raise_eperm(pid, sig):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(_os, "kill", raise_eperm)
    assert pc.pid_alive(12345) is True


def test_unknown_server_errors(monkeypatch, tmp_path):
    _fake_bg(monkeypatch, tmp_path)
    r = _run(ManageServerTool(), {"action": "restart", "name": "ghost"})
    assert r["exit_code"] == 1 and "unknown server" in r["error"]
