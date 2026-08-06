"""Doc 014 phase 3a: history assembled FROM the event log.

assemble_history() turns feed events into the exact metadata shape the
chat renderer speaks (round_texts + tool_events) — one source of truth,
zero client changes. Pinned here with the run that forced the issue: a
gemma4 turn whose reply was 'Done.' while 6.7KB of reasoning lived only
in the log.
"""
import json

from src.feed_log import assemble_history


def _ev(kind, payload, ts=1000.0):
    return {"seq": 0, "ts": ts, "kind": kind, "payload": payload}


def _tool_end(tool, status="ok", command=None, output=None, exit_code=None):
    p = {"tool": tool, "status": status}
    if command is not None:
        p["command"] = command
    if output is not None:
        p["output"] = output
    if exit_code is not None:
        p["exit_code"] = exit_code
    return _ev("tool_end", json.dumps(p))


def test_gemma_done_run_keeps_its_thinking():
    events = [
        _ev("user_msg", "build the lodge site"),
        _ev("thinking", "The user wants a lodge. Plan: templates first. "),
        _ev("thinking", "Let me start with data.json."),
        _ev("tool_start", "write_file"),
        _tool_end("write_file", "ok", command="skilodge/data.json", exit_code=0),
        _ev("reply", "Done."),
    ]
    runs = assemble_history(events)
    assert len(runs) == 1
    run = runs[0]
    assert len(run["round_texts"]) == 1
    text = run["round_texts"][0]
    assert text.startswith("<think>")
    assert "Plan: templates first." in text
    assert text.endswith("Done.")
    assert run["tool_events"] == [{
        "tool": "write_file", "round": 1, "status": "ok",
        "command": "skilodge/data.json", "exit_code": 0,
    }]


def test_multi_round_attribution():
    events = [
        _ev("user_msg", "do two things"),
        _ev("thinking", "first thing"),
        _ev("reply", "did the first"),
        _ev("thinking", "second thing"),
        _ev("tool_start", "bash"),
        _tool_end("bash", "error", command="npm run build", exit_code=1),
        _ev("reply", "second failed"),
    ]
    runs = assemble_history(events)
    (run,) = runs
    assert len(run["round_texts"]) == 2
    assert "first thing" in run["round_texts"][0]
    assert "second thing" in run["round_texts"][1]
    # the bash ran after round 1 closed -> round 2
    assert run["tool_events"][0]["round"] == 2
    assert run["tool_events"][0]["status"] == "error"


def test_two_user_turns_two_runs():
    events = [
        _ev("user_msg", "turn one"),
        _ev("reply", "answer one"),
        _ev("user_msg", "turn two"),
        _ev("tool_start", "bash"),
        _tool_end("bash", "ok"),
        _ev("reply", "answer two"),
    ]
    runs = assemble_history(events)
    assert len(runs) == 2
    assert runs[0]["round_texts"] == ["answer one"]
    assert runs[1]["round_texts"] == ["answer two"]
    assert runs[1]["tool_events"][0]["tool"] == "bash"


def test_plain_chat_turn_yields_none_slot():
    events = [
        _ev("user_msg", "hi"),
        _ev("user_msg", "are you there?"),
        _ev("reply", "yes"),
    ]
    runs = assemble_history(events)
    assert runs[0] is None            # first turn had no agent events
    assert runs[1]["round_texts"] == ["yes"]


def test_bare_name_tool_end_and_status_exit_codes():
    events = [
        _ev("user_msg", "go"),
        _ev("tool_start", "python"),
        _ev("tool_end", "python"),          # legacy bare-name payload
        _tool_end("bash", "fail"),
        _ev("reply", "report"),
    ]
    (run,) = assemble_history(events)
    py, bash = run["tool_events"]
    assert py["tool"] == "python" and py["status"] == "ok" and py["exit_code"] == 0
    assert bash["status"] == "fail" and bash["exit_code"] == 1


def test_content_mute_run_has_thinking_but_no_reply():
    # The gemma shape as the log ACTUALLY records it: thinking + tools,
    # zero reply events ("Done." never entered the round pipeline). The
    # assembler must still produce the thinking round; the ROUTE overlay
    # is responsible for appending the row-content tail.
    events = [
        _ev("user_msg", "build it"),
        _ev("thinking", "plan plan plan"),
        _ev("tool_start", "write_file"),
        _tool_end("write_file", "ok"),
    ]
    (run,) = assemble_history(events)
    assert len(run["round_texts"]) == 1
    assert run["round_texts"][0].startswith("<think>")
    assert run["round_texts"][0].endswith("</think>")


def test_tag_model_think_not_double_wrapped():
    events = [
        _ev("user_msg", "go"),
        _ev("thinking", "native reasoning"),
        _ev("reply", "<think>inline tags</think>\n\nthe answer"),
    ]
    (run,) = assemble_history(events)
    assert run["round_texts"][0].count("<think>") == 1
