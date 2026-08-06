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


def render_timeline(events):
    """The doc-014 timeline contract as a pure function over log events.

    Events are dicts with ts (epoch seconds), kind, payload. Contiguous
    thinking events collapse to one `thought:` span; a reply span lists
    the tools that ran since the previous rendered line.
    """
    import time as _t

    def _hms(ts):
        return _t.strftime("%H:%M:%S", _t.gmtime(ts))

    lines = []
    i = 0
    pending_tools = []
    while i < len(events):
        ev = events[i]
        if ev["kind"] == "user_msg":
            lines.append(f"{_hms(ev['ts'])} User: {ev['payload']}")
            pending_tools = []
            i += 1
        elif ev["kind"] == "thinking":
            start = ev["ts"]
            text = []
            while i < len(events) and events[i]["kind"] == "thinking":
                text.append(events[i]["payload"])
                end = events[i]["ts"]
                i += 1
            lines.append(f"{_hms(start)}-{_hms(end)} Agent: thought: {''.join(text)}")
        elif ev["kind"] == "tool_start":
            # The action phase (tools + reply) is ONE span in the timeline —
            # per the user's example, the reply line's clock starts when the
            # agent starts ACTING, not when the first token appears.
            if not pending_tools:
                pending_action_start = ev["ts"]
            if ev["payload"] not in pending_tools:
                pending_tools.append(ev["payload"])
            i += 1
        elif ev["kind"] == "tool_end":
            i += 1
        elif ev["kind"] == "reply":
            start = pending_action_start if pending_tools else ev["ts"]
            text = []
            while i < len(events) and events[i]["kind"] in ("reply", "tool_start", "tool_end"):
                if events[i]["kind"] == "reply":
                    text.append(events[i]["payload"])
                    end = events[i]["ts"]
                elif events[i]["kind"] == "tool_start" and events[i]["payload"] not in pending_tools:
                    pending_tools.append(events[i]["payload"])
                i += 1
            tools = f"[tools: {', '.join(pending_tools)}] " if pending_tools else ""
            lines.append(f"{_hms(start)}-{_hms(end)} Agent: {tools}replied: {''.join(text)}")
            pending_tools = []
        else:
            i += 1
    return lines


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


def test_timeline_renders_the_users_exact_example():
    """Doc 014 timeline contract — the user's example, reproduced from
    raw timestamped events, to the second."""
    T = 1750000000 - (1750000000 % 86400) + 19 * 3600 + 1   # a 19:00:01 UTC
    events = [
        {"ts": T,      "kind": "user_msg", "payload": "hi build X for me"},
        {"ts": T,      "kind": "thinking", "payload": "the user is asking me to build X for me, "},
        {"ts": T + 29, "kind": "thinking", "payload": "i should build X for him in X way."},
        {"ts": T + 29, "kind": "tool_start", "payload": "bash"},
        {"ts": T + 33, "kind": "tool_end", "payload": "bash"},
        {"ts": T + 34, "kind": "tool_start", "payload": "python"},
        {"ts": T + 40, "kind": "tool_end", "payload": "python"},
        {"ts": T + 41, "kind": "tool_start", "payload": "find_images"},
        {"ts": T + 45, "kind": "tool_end", "payload": "find_images"},
        {"ts": T + 46, "kind": "reply", "payload": "Hi! Absolutely i can build this for you like this :"},
        {"ts": T + 64, "kind": "reply", "payload": "\n[code written: X]"},
    ]
    lines = render_timeline(events)
    assert lines[0] == "19:00:01 User: hi build X for me"
    assert lines[1] == ("19:00:01-19:00:30 Agent: thought: the user is asking me to "
                        "build X for me, i should build X for him in X way.")
    assert lines[2].startswith("19:00:30-19:01:05 Agent: [tools: bash, python, find_images] replied: Hi! Absolutely")
    assert "[code written: X]" in lines[2]


def test_timeline_without_tools_or_thinking():
    T = 1750000000
    events = [
        {"ts": T, "kind": "user_msg", "payload": "hello"},
        {"ts": T + 1, "kind": "reply", "payload": "hey there"},
    ]
    lines = render_timeline(events)
    assert len(lines) == 2
    assert "thought:" not in lines[1]
    assert "[tools:" not in lines[1]
    assert lines[1].endswith("replied: hey there")


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
