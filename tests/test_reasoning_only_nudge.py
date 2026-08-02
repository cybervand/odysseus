"""A reasoning-only round must be nudged, not accepted as a finished turn.

Some reasoning models (notably gpt-oss via Ollama's harmony format) close a
round after emitting ONLY their analysis/thinking channel — no tool call, no
answer. The agent loop read that as "the model is finishing" and ended the
turn silently (observed live: gpt-oss on a multi-step prompt streamed its
reasoning panel, then stopped with zero content and zero tool calls). The
loop now detects the reasoning-only round and nudges the model to act or
answer. `_is_reasoning_only_round` is the pure decision that gate is built on.
"""
from src.agent_loop import _is_reasoning_only_round


def test_reasoning_present_no_text_no_tools_is_reasoning_only():
    assert _is_reasoning_only_round(
        "We need to run the python tool to check the library.",
        "",
        False,
    ) is True


def test_tool_call_present_is_not_reasoning_only():
    # A round that produced a tool call is progress, never a stall.
    assert _is_reasoning_only_round(
        "Let me call the tool.",
        "",
        True,
    ) is False


def test_visible_answer_present_is_not_reasoning_only():
    # The model gave a real answer — reasoning alongside it is fine.
    assert _is_reasoning_only_round(
        "The user asked for X.",
        "Here is your answer.",
        False,
    ) is False


def test_empty_reasoning_is_not_reasoning_only():
    # Nothing at all (no reasoning, no text, no tools) is the separate
    # empty-response case handled elsewhere, not a reasoning-only stall.
    assert _is_reasoning_only_round("", "", False) is False


def test_whitespace_only_reasoning_is_not_reasoning_only():
    assert _is_reasoning_only_round("   \n  ", "", False) is False


def test_whitespace_only_text_still_counts_as_no_visible_answer():
    # Reasoning present, "text" is only whitespace -> still a stall.
    assert _is_reasoning_only_round("Thinking hard.", "   ", False) is True
