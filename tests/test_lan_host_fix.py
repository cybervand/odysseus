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


def test_vite_gets_host_flag(tmp_path):
    cwd = _pkg(tmp_path, {"vite": "^5.0.0"})
    cmd, note = _lan_host_fix("npm run dev", cwd)
    assert cmd == "npm run dev -- --host 0.0.0.0"
    assert "vite" in note


def test_next_gets_host_flag(tmp_path):
    cwd = _pkg(tmp_path, {"next": "^14.0.0"})
    cmd, note = _lan_host_fix("npm run dev", cwd)
    assert cmd == "npm run dev -- -H 0.0.0.0"
    assert "next" in note


def test_existing_host_binding_is_kept(tmp_path):
    cwd = _pkg(tmp_path, {"vite": "^5.0.0"})
    cmd, note = _lan_host_fix("npm run dev -- --host 0.0.0.0", cwd)
    assert cmd == "npm run dev -- --host 0.0.0.0"
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


def test_vite_in_command_without_package_json():
    cmd, note = _lan_host_fix("npx vite dev", "/nowhere")
    assert cmd == "npx vite dev -- --host 0.0.0.0"
    assert "vite" in note
