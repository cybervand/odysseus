"""Production feed log (doc 014 phase 1) — the spike's semantics, now in src.

Covers: durable append/tail/resume, the ok/error/fail derivation from
real tool results, incognito routing to the ephemeral log, and the
timeline rendering with JSON tool_end payloads (the production shape).
"""
import json

import src.feed_log as fl


def _mklog(tmp_path):
    return fl.EventLog(str(tmp_path / "feed.db"))


def test_append_tail_resume(tmp_path):
    log = _mklog(tmp_path)
    for i in range(4):
        log.append("s1", "reply", f"r{i}")
    assert [e["seq"] for e in log.tail("s1", 0)] == [0, 1, 2, 3]
    assert [e["payload"] for e in log.tail("s1", 2)] == ["r2", "r3"]
    assert log.head("s1") == 3
    assert log.is_replaying("s1", 1) and not log.is_replaying("s1", 3)


def test_tool_status_derivation():
    assert fl.tool_status({"output": "done", "exit_code": 0}) == "ok"
    assert fl.tool_status({"output": "STDERR: lsof: not found", "exit_code": 127}) == "error"
    assert fl.tool_status({"error": "find_images: no verified images found", "exit_code": 1}) == "fail"
    assert fl.tool_status({"output": "x"}) == "ok"          # no exit_code = ok
    assert fl.tool_status("garbage") == "fail"


def test_emit_routes_incognito_to_ephemeral(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "_DB_PATH", str(tmp_path / "feed.db"))
    monkeypatch.setattr(fl, "_durable", None)
    monkeypatch.setattr(fl, "_ephemeral", fl.EphemeralEventLog())
    monkeypatch.setattr(fl, "_run_registry", {})

    fl.register_run("priv", incognito=True)
    fl.register_run("pub", incognito=False)
    fl.emit("priv", "reply", "secret")
    fl.emit("pub", "reply", "public")

    assert fl.get_log(incognito=False).tail("priv", 0) == []      # nothing durable
    assert fl.get_log(incognito=True).tail("priv", 0)[0]["payload"] == "secret"
    assert fl.get_log(incognito=False).tail("pub", 0)[0]["payload"] == "public"


def test_emit_never_raises(monkeypatch):
    class Boom:
        def append(self, *a, **k):
            raise RuntimeError("db on fire")
    monkeypatch.setattr(fl, "get_log", lambda incognito=False: Boom())
    fl.emit("s", "reply", "text")   # must not raise


def test_timeline_with_json_tool_ends():
    T = 1750000000
    events = [
        {"ts": T, "kind": "user_msg", "payload": "build it"},
        {"ts": T + 1, "kind": "tool_start", "payload": "bash"},
        {"ts": T + 2, "kind": "tool_end", "payload": json.dumps({"tool": "bash", "status": "error"})},
        {"ts": T + 3, "kind": "tool_start", "payload": "find_images"},
        {"ts": T + 4, "kind": "tool_end", "payload": json.dumps({"tool": "find_images", "status": "ok"})},
        {"ts": T + 5, "kind": "reply", "payload": "done"},
    ]
    lines = fl.render_timeline(events)
    assert "[tools: bash error, find_images ok]" in lines[1]
    assert lines[1].endswith("replied: done")
