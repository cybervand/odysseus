"""The feed event log — doc 014 phase 1 (dual-write).

One durable, ordered, per-session log of everything the feed shows:
user messages, per-round thinking and reply text, tool calls with the
ok/error/fail status vocabulary, run state. All future consumers
(history, live tails, resume, the timeline) read THIS; for now it
dual-writes alongside the legacy pipeline, changing nothing.

Incognito sessions route to an in-RAM ephemeral log with the identical
interface — a constructor swap, not a scatter of guards. Eviction at
session end IS the privacy guarantee.
"""
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Dict, Optional, Tuple

from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(DATA_DIR, "feed_events.db")


class EventLog:
    """Durable per-session event log (SQLite WAL, per-call connections)."""

    def __init__(self, path: str = _DB_PATH):
        self._path = str(path)
        self._lock = threading.Lock()
        con = self._con()
        con.execute(
            "CREATE TABLE IF NOT EXISTS feed_events ("
            " session_id TEXT NOT NULL,"
            " seq INTEGER NOT NULL,"
            " ts REAL NOT NULL,"
            " kind TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " PRIMARY KEY (session_id, seq))"
        )
        con.execute("PRAGMA journal_mode=WAL")
        con.commit()
        con.close()

    def _con(self):
        return sqlite3.connect(self._path, timeout=10)

    def append(self, session_id: str, kind: str, payload: str, ts: Optional[float] = None) -> int:
        with self._lock:
            con = self._con()
            try:
                seq = con.execute(
                    "SELECT COALESCE(MAX(seq), -1) + 1 FROM feed_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
                con.execute(
                    "INSERT INTO feed_events (session_id, seq, ts, kind, payload) VALUES (?,?,?,?,?)",
                    (session_id, seq, ts if ts is not None else time.time(), kind, payload),
                )
                con.commit()
                return seq
            finally:
                con.close()

    def head(self, session_id: str) -> int:
        con = self._con()
        try:
            return con.execute(
                "SELECT COALESCE(MAX(seq), -1) FROM feed_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
        finally:
            con.close()

    def tail(self, session_id: str, from_seq: int = 0, limit: int = 5000):
        con = self._con()
        try:
            cur = con.execute(
                "SELECT seq, ts, kind, payload FROM feed_events"
                " WHERE session_id = ? AND seq >= ? ORDER BY seq LIMIT ?",
                (session_id, from_seq, limit),
            )
            return [{"seq": s, "ts": t, "kind": k, "payload": p}
                    for s, t, k, p in cur.fetchall()]
        finally:
            con.close()

    def is_replaying(self, session_id: str, position: int) -> bool:
        return position < self.head(session_id)

    def latest(self, session_id: str, kind: str) -> Optional[str]:
        """Payload of the newest event of `kind`, or None (doc 016: the
        ledger is stored latest-wins as its own event kind)."""
        con = self._con()
        try:
            row = con.execute(
                "SELECT payload FROM feed_events WHERE session_id = ? AND kind = ?"
                " ORDER BY seq DESC LIMIT 1",
                (session_id, kind),
            ).fetchone()
            return row[0] if row else None
        finally:
            con.close()


class EphemeralEventLog:
    """Incognito's feed: identical interface, RAM ring, evicted on end."""

    def __init__(self):
        self._events: Dict[str, list] = {}
        self._lock = threading.Lock()

    def append(self, session_id: str, kind: str, payload: str, ts: Optional[float] = None) -> int:
        with self._lock:
            evs = self._events.setdefault(session_id, [])
            seq = len(evs)
            evs.append({"seq": seq, "ts": ts if ts is not None else time.time(),
                        "kind": kind, "payload": payload})
            return seq

    def head(self, session_id: str) -> int:
        return len(self._events.get(session_id, [])) - 1

    def tail(self, session_id: str, from_seq: int = 0, limit: int = 5000):
        return [dict(e) for e in self._events.get(session_id, []) if e["seq"] >= from_seq][:limit]

    def is_replaying(self, session_id: str, position: int) -> bool:
        return position < self.head(session_id)

    def latest(self, session_id: str, kind: str) -> Optional[str]:
        for e in reversed(self._events.get(session_id, [])):
            if e["kind"] == kind:
                return e["payload"]
        return None

    def end_session(self, session_id: str) -> None:
        with self._lock:
            self._events.pop(session_id, None)


# ── Module singletons + run registry ──

_durable: Optional[EventLog] = None
_ephemeral = EphemeralEventLog()
# session_id -> incognito flag, registered by the agent loop for the
# duration of a run so tool_execution can emit without threading params.
_run_registry: Dict[str, bool] = {}


def get_log(incognito: bool = False):
    global _durable
    if incognito:
        return _ephemeral
    if _durable is None:
        _durable = EventLog()
    return _durable


def register_run(session_id: str, incognito: bool) -> None:
    if session_id:
        _run_registry[session_id] = bool(incognito)


def unregister_run(session_id: str) -> None:
    _run_registry.pop(session_id, None)
    if session_id and _run_registry.get(session_id):
        _ephemeral.end_session(session_id)


def emit(session_id: str, kind: str, payload: str, incognito: Optional[bool] = None) -> None:
    """Fire-and-forget append; never lets feed logging break the feed."""
    if not session_id or not payload and kind not in ("run_state",):
        return
    try:
        if incognito is None:
            incognito = _run_registry.get(session_id, False)
        get_log(incognito).append(session_id, kind, str(payload))
    except Exception as e:
        logger.warning("[feed] emit failed (%s/%s): %s", session_id, kind, e)


def tool_status(result: dict) -> str:
    """Doc 014 status vocabulary, derived mechanically from a tool result:
    ok = executed, succeeded; error = executed but the WORK failed
    (exit_code != 0); fail = the tool itself couldn't do its job."""
    if not isinstance(result, dict):
        return "fail"
    if result.get("error"):
        return "fail"
    try:
        code = int(result.get("exit_code", 0) or 0)
    except (TypeError, ValueError):
        return "ok"
    return "ok" if code == 0 else "error"


# ── Timeline rendering (the doc-014 contract, from the spike) ──

_RANK = {"ok": 0, "error": 1, "fail": 2}


def _hms(ts):
    return time.strftime("%H:%M:%S", time.gmtime(ts))


def _fmt_tools(tools):
    return "[tools: " + ", ".join(f"{n} {s}" for n, s in tools) + "] "


def _record_tool(tools, name, status):
    for idx, (n, s) in enumerate(tools):
        if n == name:
            if _RANK.get(status, 0) > _RANK.get(s, 0):
                tools[idx] = (n, status)
            return
    tools.append((name, status))


def render_timeline(events):
    """Pure function: log events -> timeline lines. Contiguous thinking
    collapses to one span; tools attach to the phase they RAN IN (a tool
    belongs to thinking only if more thinking follows it before the
    reply); action spans start at the first tool; statuses aggregate
    worst-first per tool."""
    lines = []
    i = 0
    pending_tools = []
    pending_action_start = None
    while i < len(events):
        ev = events[i]
        if ev["kind"] == "user_msg":
            lines.append(f"{_hms(ev['ts'])} User: {ev['payload']}")
            pending_tools = []
            i += 1
        elif ev["kind"] == "thinking":
            start = ev["ts"]
            end = ev["ts"]
            text = []
            think_tools = []

            def _more_thinking_ahead(j):
                while j < len(events) and events[j]["kind"] in ("tool_start", "tool_end"):
                    j += 1
                return j < len(events) and events[j]["kind"] == "thinking"

            while i < len(events) and events[i]["kind"] in ("thinking", "tool_start", "tool_end"):
                e = events[i]
                if e["kind"] == "thinking":
                    text.append(e["payload"])
                    end = e["ts"]
                elif e["kind"] == "tool_start":
                    if not _more_thinking_ahead(i):
                        break
                    if not any(n == e["payload"] for n, _ in think_tools):
                        think_tools.append((e["payload"], "ok"))
                        end = e["ts"]
                elif e["kind"] == "tool_end":
                    _record_tool(think_tools, _tool_name(e), _tool_stat(e))
                i += 1
            tools = _fmt_tools(think_tools) if think_tools else ""
            lines.append(f"{_hms(start)}-{_hms(end)} Agent: {tools}thought: {''.join(text)}")
        elif ev["kind"] == "tool_start":
            if not pending_tools:
                pending_action_start = ev["ts"]
            if not any(n == ev["payload"] for n, _ in pending_tools):
                pending_tools.append((ev["payload"], "ok"))
            i += 1
        elif ev["kind"] == "tool_end":
            _record_tool(pending_tools, _tool_name(ev), _tool_stat(ev))
            i += 1
        elif ev["kind"] == "reply":
            start = pending_action_start if pending_tools else ev["ts"]
            end = ev["ts"]
            text = []
            while i < len(events) and events[i]["kind"] in ("reply", "tool_start", "tool_end"):
                e = events[i]
                if e["kind"] == "reply":
                    text.append(e["payload"])
                    end = e["ts"]
                elif e["kind"] == "tool_start" and not any(n == e["payload"] for n, _ in pending_tools):
                    pending_tools.append((e["payload"], "ok"))
                elif e["kind"] == "tool_end":
                    _record_tool(pending_tools, _tool_name(e), _tool_stat(e))
                i += 1
            tools = _fmt_tools(pending_tools) if pending_tools else ""
            lines.append(f"{_hms(start)}-{_hms(end)} Agent: {tools}replied: {''.join(text)}")
            pending_tools = []
            pending_action_start = None
        else:
            i += 1
    return lines


# ── History assembly (doc 014 phase 3a) ──
# The log becomes the history source: events -> the exact metadata shape
# the chat renderer already speaks (round_texts + tool_events), so the
# client needs zero changes and legacy saved metadata demotes to the
# pre-log fallback.


def assemble_history(events):
    """Pure function: log events -> per-run renderer-shape metadata.

    Returns a list of runs, one per user_msg (events before the first
    user_msg fold into the first run): each is {"round_texts": [...],
    "tool_events": [...]}. Thinking persists inside round text as a
    <think> block (the renderer's processWithThinking parses it); tools
    carry command/output/exit_code when the log has them (post-enrichment
    events) and 1-based round attribution."""
    runs = []
    cur = None

    def _new_run():
        return {"round_texts": [], "tool_events": [], "_thinking": [], "_reply": [],
                "_open_tools": {}}

    def _close_round(run):
        think = "".join(run["_thinking"]).strip()
        reply = "".join(run["_reply"]).strip()
        if not think and not reply:
            return
        text = reply
        if think and "<think>" not in reply:
            text = (f"<think>\n{think}\n</think>\n\n" + reply).strip()
        run["round_texts"].append(text)
        run["_thinking"] = []
        run["_reply"] = []

    for ev in events:
        kind = ev.get("kind")
        if kind == "user_msg":
            if cur is not None:
                _close_round(cur)
                runs.append(cur)
            cur = _new_run()
            continue
        if cur is None:
            cur = _new_run()
        if kind == "thinking":
            # thinking after a reply began = a new round starting
            if cur["_reply"]:
                _close_round(cur)
            cur["_thinking"].append(ev.get("payload") or "")
        elif kind == "reply":
            cur["_reply"].append(ev.get("payload") or "")
        elif kind == "tool_start":
            pass  # membership recorded at tool_end (which has the status)
        elif kind == "tool_end":
            p = ev.get("payload") or ""
            info = {}
            if isinstance(p, str) and p.startswith("{"):
                try:
                    info = json.loads(p)
                except json.JSONDecodeError:
                    info = {"tool": p}
            else:
                info = {"tool": p}
            # A tool ending means the current text belongs to THIS round —
            # close it now. Without this, rounds only closed on
            # thinking-after-reply, so text-tool-text-tool runs concatenated
            # every reply into ONE block and attributed every tool to round
            # 1: the renderer drew one compressed bubble plus a monolithic
            # card column ("messages between tool calls squashed to top or
            # bottom", 2026-08-07).
            if cur["_reply"] or cur["_thinking"]:
                _close_round(cur)
            elif not cur["round_texts"] and not cur["tool_events"]:
                # Tools before any text: hold slot 1 so later text lands in
                # slot 2 and renders BELOW this thread, not above it.
                cur["round_texts"].append("")
            round_num = max(1, len(cur["round_texts"]))
            tev = {"tool": info.get("tool", "?"), "round": round_num,
                   "status": info.get("status", "ok")}
            if info.get("command"):
                tev["command"] = info["command"]
            if info.get("output"):
                tev["output"] = info["output"]
            if info.get("exit_code") is not None:
                tev["exit_code"] = info["exit_code"]
            else:
                tev["exit_code"] = 0 if tev["status"] == "ok" else 1
            cur["tool_events"].append(tev)
    if cur is not None:
        _close_round(cur)
        runs.append(cur)
    out = []
    for r in runs:
        if r["round_texts"] or r["tool_events"]:
            out.append({"round_texts": r["round_texts"], "tool_events": r["tool_events"]})
        else:
            out.append(None)  # user_msg with no agent activity (e.g. plain chat rows)
    return out


def _tool_name(ev) -> str:
    """tool_end payload is either a bare name or JSON {tool, status}."""
    p = ev.get("payload", "")
    if isinstance(p, str) and p.startswith("{"):
        try:
            return json.loads(p).get("tool", p)
        except json.JSONDecodeError:
            return p
    return p


def _tool_stat(ev) -> str:
    p = ev.get("payload", "")
    if isinstance(p, str) and p.startswith("{"):
        try:
            return json.loads(p).get("status", "ok")
        except json.JSONDecodeError:
            return "ok"
    return ev.get("status", "ok")
