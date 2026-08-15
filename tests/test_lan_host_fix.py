"""Tests for the dev-server LAN host fix (doc 017 teaching family).

Vite and Next bind the loopback address by default. A model started
'npm run dev' and the user's browser got a refused connection while
the container said 200 (hawaii-history-react, 2026-08-12). The fix
adds the correct host flag for known dev servers and notes the change.
"""

import json

from src.bg_jobs import _lan_host_fix


def _pkg(tmp_path, deps):
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": deps}), encoding="utf-8")
    return str(tmp_path)


def test_vite_gets_host_and_port_flags(tmp_path):
    cwd = _pkg(tmp_path, {"vite": "^5.0.0"})
    cmd, note = _lan_host_fix("npm run dev", cwd)
    assert cmd == "npm run dev -- --host 0.0.0.0 --port $PORT"
    assert "vite" in note


def test_next_gets_host_and_port_flags(tmp_path):
    cwd = _pkg(tmp_path, {"next": "^14.0.0"})
    cmd, note = _lan_host_fix("npm run dev", cwd)
    assert cmd == "npm run dev -- -H 0.0.0.0 -p $PORT"
    assert "next" in note


def test_existing_host_binding_still_gets_port(tmp_path):
    # vite never reads the PORT env var: without the port flag the
    # registry's assigned port is fiction (registry said 13000, vite
    # served 5173 — 2026-08-15).
    cwd = _pkg(tmp_path, {"vite": "^5.0.0"})
    cmd, note = _lan_host_fix("npm run dev -- --host 0.0.0.0", cwd)
    assert cmd == "npm run dev -- --host 0.0.0.0 --port $PORT"
    assert note is not None


def test_existing_separator_never_doubled(tmp_path):
    # A second `--` makes vite read --host as a positional and silently
    # stay on the loopback (2026-08-15, hawaii-history).
    cwd = _pkg(tmp_path, {"vite": "^5.0.0"})
    cmd, note = _lan_host_fix("npm run dev -- --port 13000 --strictPort", cwd)
    assert cmd == "npm run dev -- --port 13000 --strictPort --host 0.0.0.0"
    assert cmd.count(" -- ") == 1


def test_fully_specified_command_untouched(tmp_path):
    cwd = _pkg(tmp_path, {"vite": "^5.0.0"})
    cmd, note = _lan_host_fix("npm run dev -- --host 0.0.0.0 --port $PORT", cwd)
    assert cmd == "npm run dev -- --host 0.0.0.0 --port $PORT"
    assert note is None


def test_non_dev_command_is_kept():
    cmd, note = _lan_host_fix("python -m http.server $PORT", "/nowhere")
    assert cmd == "python -m http.server $PORT"
    assert note is None


def test_unknown_dev_server_gets_a_note_only(tmp_path):
    cwd = _pkg(tmp_path, {"some-framework": "1.0.0"})
    cmd, note = _lan_host_fix("npm run dev", cwd)
    assert cmd == "npm run dev"
    assert "0.0.0.0" in note


def test_direct_vite_gets_flags_without_separator():
    # `npx vite` takes flags directly; a `--` would turn them into
    # positionals (the old behavior appended one — that was the bug).
    cmd, note = _lan_host_fix("npx vite dev", "/nowhere")
    assert cmd == "npx vite dev --host 0.0.0.0 --port $PORT"
    assert " -- " not in cmd
    assert "vite" in note


def test_server_jobs_stay_out_of_followups(tmp_path, monkeypatch):
    """A registry server must not page the chat when it dies (deploys
    kill in-container servers; the reconciler owns revival)."""
    from src import bg_jobs

    monkeypatch.setattr(bg_jobs, "refresh", lambda: {
        "j-server": {"id": "j-server", "status": "failed", "followed_up": False},
        "j-task": {"id": "j-task", "status": "done", "followed_up": False},
    })
    monkeypatch.setattr(bg_jobs, "_load_servers",
                        lambda: {"hawaii": {"job_id": "j-server"}})
    pending = bg_jobs.pending_followups()
    assert [r["id"] for r in pending] == ["j-task"]
