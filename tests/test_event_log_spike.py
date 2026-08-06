"""Spike for doc 014 (live chat feed, option D): a durable per-session
event log as the single source of truth. NOT wired into production —
this file both defines the prototype and proves its semantics, so a
later promotion into src/ is mechanical.

Semantics proven here:
  - append assigns gapless monotonically increasing seq per session
  - tail(from_seq) returns exactly the missed events, no dupes/gaps
  - replay/live boundary is a comparison (pos < head), not a feature
  - the log survives "process death" (fresh instance, same storage)
  - independent consumers at different positions don't interfere
"""
import sqlite3

import pytest


class EventLog:
    """Minimal durable per-session event log (SQLite, stdlib only)."""

    def __init__(self, path):
        self._path = str(path)
        con = self._con()
        con.execute(
            "CREATE TABLE IF NOT EXISTS feed_events ("
            " session_id TEXT NOT NULL,"
            " seq INTEGER NOT NULL,"
            " kind TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " PRIMARY KEY (session_id, seq))"
        )
        con.commit()
        con.close()

    def _con(self):
        return sqlite3.connect(self._path)

    def append(self, session_id: str, kind: str, payload: str) -> int:
        con = self._con()
        try:
            cur = con.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM feed_events WHERE session_id = ?",
                (session_id,),
            )
            seq = cur.fetchone()[0]
            con.execute(
                "INSERT INTO feed_events (session_id, seq, kind, payload) VALUES (?,?,?,?)",
                (session_id, seq, kind, payload),
            )
            con.commit()
            return seq
        finally:
            con.close()

    def head(self, session_id: str) -> int:
        con = self._con()
        try:
            cur = con.execute(
                "SELECT COALESCE(MAX(seq), -1) FROM feed_events WHERE session_id = ?",
                (session_id,),
            )
            return cur.fetchone()[0]
        finally:
            con.close()

    def tail(self, session_id: str, from_seq: int = 0):
        """Events with seq >= from_seq, in order. A client that renders
        these and remembers the last seq can resume with zero loss and
        zero duplication — this is SSE Last-Event-ID shaped."""
        con = self._con()
        try:
            cur = con.execute(
                "SELECT seq, kind, payload FROM feed_events"
                " WHERE session_id = ? AND seq >= ? ORDER BY seq",
                (session_id, from_seq),
            )
            return [{"seq": s, "kind": k, "payload": p} for s, k, p in cur.fetchall()]
        finally:
            con.close()

    def is_replaying(self, session_id: str, position: int) -> bool:
        """The replay/live badge is a COMPARISON, not a feature."""
        return position < self.head(session_id)


@pytest.fixture()
def log(tmp_path):
    return EventLog(tmp_path / "feed.db")


def test_append_assigns_gapless_sequence(log):
    seqs = [log.append("s1", "delta", f"tok{i}") for i in range(5)]
    assert seqs == [0, 1, 2, 3, 4]
    # Interleaved session doesn't disturb s1's sequence.
    log.append("s2", "delta", "other")
    assert log.append("s1", "delta", "tok5") == 5


def test_tail_resume_no_gaps_no_dupes(log):
    for i in range(6):
        log.append("s1", "delta", f"tok{i}")
    first = log.tail("s1", 0)
    assert [e["seq"] for e in first] == [0, 1, 2, 3, 4, 5]
    # Client saw through seq 3, resumes from 4 — exactly the missed tail.
    resumed = log.tail("s1", 4)
    assert [e["payload"] for e in resumed] == ["tok4", "tok5"]
    # Full replay then resume covers every event exactly once.
    seen = [e["seq"] for e in log.tail("s1", 0)]
    assert seen == sorted(set(seen))


def test_replay_live_boundary_is_a_comparison(log):
    for i in range(3):
        log.append("s1", "delta", f"t{i}")
    assert log.is_replaying("s1", position=1) is True   # behind head → replay badge
    assert log.is_replaying("s1", position=2) is False  # at head → live


def test_survives_process_death(tmp_path):
    a = EventLog(tmp_path / "feed.db")
    a.append("s1", "user_msg", "hello")
    a.append("s1", "delta", "partial reply the user watched")
    # "Process dies": new instance, same storage — nothing lost.
    b = EventLog(tmp_path / "feed.db")
    events = b.tail("s1", 0)
    assert [e["payload"] for e in events] == ["hello", "partial reply the user watched"]
    # And appends continue the sequence without collision.
    assert b.append("s1", "run_state", "interrupted") == 2


def test_independent_consumers(log):
    for i in range(4):
        log.append("s1", "delta", f"t{i}")
    watcher_pos = 0
    browser_pos = 3
    watcher_view = log.tail("s1", watcher_pos)
    browser_view = log.tail("s1", browser_pos)
    assert len(watcher_view) == 4          # cold observer replays all
    assert len(browser_view) == 1          # live tab gets only the newest
    # Neither consumer's reads changed the log.
    assert log.head("s1") == 3
