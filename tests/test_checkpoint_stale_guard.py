"""Tests for the checkpoint stale guard (twin-message bug, 2026-08-12).

A run saved its reply, then a late agent round wrote a new checkpoint.
The orphan reaper promoted that stale checkpoint and the transcript
showed the same reply two times. The guard compares the checkpoint with
the last assistant row and clears a stale checkpoint without promotion.
"""

import uuid

from src.run_checkpoint import (
    clear_partial,
    promote_if_orphaned,
    read_partial,
    write_partial,
)


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class _Sess:
    def __init__(self, history):
        self.history = history


class _Manager:
    def __init__(self, history):
        self._sess = _Sess(history)
        self.added = []

    def get_session(self, session_id):
        return self._sess

    def add_message(self, session_id, msg):
        self.added.append(msg)


def _sid():
    return "test-ckpt-" + uuid.uuid4().hex[:10]


def test_stale_checkpoint_clears_without_twin():
    sid = _sid()
    reply = "Your site is live. It runs on port 13002. " * 5
    write_partial(sid, "<think>plan</think>" + reply, 6)
    mgr = _Manager([_Msg("user", "build it"), _Msg("assistant", reply)])
    try:
        assert promote_if_orphaned(sid, mgr, run_status="done") is False
        assert mgr.added == []            # no twin message
        assert read_partial(sid) is None  # checkpoint cleared
    finally:
        clear_partial(sid)


def test_genuine_orphan_still_promotes():
    sid = _sid()
    write_partial(sid, "Half-built answer the DB never got.", 3)
    mgr = _Manager([_Msg("user", "build it"),
                    _Msg("assistant", "An unrelated earlier reply.")])
    try:
        assert promote_if_orphaned(sid, mgr, run_status="done") is True
        assert len(mgr.added) == 1
        assert "recovered" in mgr.added[0].content
    finally:
        clear_partial(sid)


def test_running_run_is_left_alone():
    sid = _sid()
    write_partial(sid, "Streaming right now.", 2)
    mgr = _Manager([])
    try:
        assert promote_if_orphaned(sid, mgr, run_status="running") is False
        assert read_partial(sid) is not None  # checkpoint kept
    finally:
        clear_partial(sid)
