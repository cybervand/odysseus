"""Unconvertible native tool calls must be reported, not silently dropped.

A native tool call that fails to convert (hallucinated tool name like `cat`,
or unusable arguments) means the model TRIED to act. When every call in a
round fails this way, the agent loop used to see "no tool blocks" and treat
the round as a final answer — ending the turn mid-task with no signal to the
model or the user (observed live: a model finishing a multi-step task by
calling a nonexistent `cat` tool, which silently ended the run before its
final report). _resolve_tool_blocks now returns the failed calls so the loop
can feed the error back and give the model another round.
"""
import src.agent_loop as al


def test_unknown_tool_reported_as_failed_not_known():
    native = [{"name": "cat", "arguments": '{"file_path": "/tmp/x"}', "id": "A"}]
    tool_blocks, used_native, converted, failed, _ = al._resolve_tool_blocks("", native, 1)
    assert tool_blocks == []
    assert used_native is False
    assert converted == []
    assert len(failed) == 1
    assert failed[0]["name"] == "cat"
    assert failed[0]["known"] is False


def test_known_tool_with_unparseable_args_reported_as_failed_known():
    native = [{"name": "web_search", "arguments": "not-json{{{", "id": "A"}]
    tool_blocks, used_native, converted, failed, _ = al._resolve_tool_blocks("", native, 1)
    assert tool_blocks == []
    assert len(failed) == 1
    assert failed[0]["name"] == "web_search"
    assert failed[0]["known"] is True


def test_successful_conversion_reports_no_failures():
    native = [{"name": "web_search", "arguments": '{"query": "hi"}', "id": "A"}]
    tool_blocks, used_native, converted, failed, _ = al._resolve_tool_blocks("", native, 1)
    assert len(tool_blocks) == 1
    assert failed == []


def test_mixed_round_reports_only_the_failed_call():
    native = [
        {"name": "cat", "arguments": "{}", "id": "A"},
        {"name": "web_search", "arguments": '{"query": "hi"}', "id": "B"},
    ]
    tool_blocks, used_native, converted, failed, _ = al._resolve_tool_blocks("", native, 1)
    assert len(tool_blocks) == 1
    assert [c["name"] for c in converted] == ["web_search"]
    assert [f["name"] for f in failed] == ["cat"]
    assert failed[0]["known"] is False
