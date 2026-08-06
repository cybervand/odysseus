"""Registry consistency for src/dialect_profiles.py (docs 009 + 012).

The registry is the single index of per-model-family tool-calling
adaptations. These tests enforce its structural invariants so a profile
edit can't silently ship an unparseable note or give a diagnosed-only
family runtime behavior.
"""
import src.agent_loop as _al  # noqa: F401 — breaks tool_parsing circular import
from src.dialect_profiles import (
    PROFILES,
    fenced_fallback_for,
    profile_for,
    turn_note_for,
)
from src.tool_parsing import parse_tool_blocks


def test_every_turn_note_parses_through_our_own_chain():
    # Doc 012 v1 lesson, formalized: the shapes a DIALECT note TEACHES must
    # parse via our chain — in the strictest pass (skip_fenced=True,
    # api-model primary), so no note can depend on the fenced fallback to be
    # understood. BEHAVIORAL notes (conduct steering for models whose
    # emission is already clean, e.g. gemma4's content-mute note) must
    # contain NO tool shapes at all — shapes in a behavioral note could
    # destabilize a working dialect (the same v1 lesson, other direction).
    noted = [p for p in PROFILES if p.turn_note]
    assert noted, "expected at least the glm and deepseek notes"
    for p in noted:
        blocks = parse_tool_blocks(p.turn_note, skip_fenced=True)
        types = [b.tool_type for b in blocks]
        if p.note_kind == "behavioral":
            assert types == [], (
                f"{p.family}: behavioral note must teach no tool shapes, parsed {types}"
            )
        else:
            assert types == ["bash", "write_file"], (
                f"{p.family}: note examples parsed as {types}"
            )


def test_diagnosed_profiles_have_no_runtime_knobs():
    for p in PROFILES:
        if p.status == "diagnosed":
            assert p.turn_note is None and not p.fenced_fallback, (
                f"{p.family} is diagnosed-only but has runtime behavior"
            )


def test_match_keys_are_lowercase():
    for p in PROFILES:
        assert p.match, f"{p.family}: empty match tuple"
        for k in p.match:
            assert k == k.lower(), f"{p.family}: match key {k!r} not lowercase"


def test_routing_of_known_fleet_models():
    assert profile_for("deepseek-r1:14b").family == "deepseek-r1-fenced"
    assert profile_for("glm4:9b").family == "glm-bare-invocation"
    assert profile_for("hermes3:8b").family == "hermes-fenced"
    assert profile_for("llama3.1:8b").family == "llama3-json"
    assert profile_for("gpt-oss:20b").family == "harmony-builtins"
    assert profile_for("gpt-4o") is None
    assert profile_for(None) is None
    assert profile_for("") is None


def test_runtime_helpers():
    assert fenced_fallback_for("deepseek-r1:14b") is True
    assert fenced_fallback_for("hermes3:8b") is True
    assert fenced_fallback_for("glm4:9b") is False
    assert fenced_fallback_for("qwen3-coder:30b") is False
    assert turn_note_for("glm4:9b")
    assert turn_note_for("deepseek-r1:14b")
    assert turn_note_for("qwen3-coder:30b") is None


def test_parser_only_families_have_no_knobs():
    # qwen matches broadly (including the odysseus-qwen3 finetunes) — it must
    # stay a pure index entry or every qwen variant would get injected notes.
    p = profile_for("qwen3.5:9b")
    assert p.family == "qwen-function-xml"
    assert p.turn_note is None and p.fenced_fallback is False
