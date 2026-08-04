"""Subprocess tool output must be readable by models and humans.

Live specimen: `npx eslint --init` rendered an interactive wizard through
the pipe — ANSI color/cursor codes ("[1m[36m[?25l...") reached the model's
context and the chat UI as literal garbage, then the command died (exit 13,
no TTY) and the verifier passed the turn anyway because the failure was a
quiet "(exit 13)" suffix in its evidence.
"""
import asyncio

import pytest

import src.tool_execution as tool_execution
from src.agent_loop import _build_actions_snapshot
from src.agent_tools.subprocess_tools import _strip_ansi, BashTool


def test_strip_ansi_removes_csi_and_osc():
    raw = "\x1b[1m@eslint/create-config: v2.0.0\x1b[22m\n\x1b[?25l\x1b[36m?\x1b[39m What do you want to lint?\x1b[6A\x1b[32G\x1b[?25h"
    clean = _strip_ansi(raw)
    assert "\x1b" not in clean
    assert "@eslint/create-config: v2.0.0" in clean
    assert "What do you want to lint?" in clean


def test_strip_ansi_leaves_plain_text_untouched():
    s = "added 27 packages, and audited 28 packages in 10s"
    assert _strip_ansi(s) is s  # fast path: no escape byte, same object


def test_bash_output_is_ansi_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(tool_execution, "agent_cwd", lambda: str(tmp_path))
    res = asyncio.run(BashTool().execute(
        "printf '\\033[1mBOLD\\033[0m plain'", {"progress_cb": None, "subproc_env": None}
    ))
    assert res.get("exit_code") == 0
    assert "\x1b" not in res["output"]
    assert "BOLD plain" in res["output"]


def test_snapshot_screams_about_failures():
    events = [
        {"tool": "bash", "command": "npx eslint --init", "output": "wizard died", "exit_code": 13},
        {"tool": "bash", "command": "echo ok", "output": "ok", "exit_code": 0},
    ]
    snap = _build_actions_snapshot(events)
    assert "FAILED (exit 13)" in snap
    assert "UNMET" in snap          # tells the judge what a failure means
    assert "FAILED" not in snap.split("echo ok")[1]  # success stays quiet
