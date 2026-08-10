"""Unit tests for src/thinking_controls.py — command-menu overrides."""

from src.thinking_controls import (
    apply_to_ollama_native,
    effort_override,
    reset_overrides,
    set_overrides,
)


def _with(tm, ef):
    return set_overrides(tm, ef)


def test_defaults_leave_payload_untouched():
    tokens = _with("", "")
    try:
        p = {}
        apply_to_ollama_native(p, "gemma4:e2b")
        assert p == {}
        assert effort_override() == ""
    finally:
        reset_overrides(tokens)


def test_invalid_values_coerce_to_defaults():
    tokens = _with("banana", "extreme")
    try:
        p = {}
        apply_to_ollama_native(p, "gemma4:12b")
        assert p == {}
    finally:
        reset_overrides(tokens)


def test_off_suppresses_thinking_for_normal_models():
    tokens = _with("off", "")
    try:
        p = {}
        apply_to_ollama_native(p, "gemma4:12b")
        assert p["think"] is False
    finally:
        reset_overrides(tokens)


def test_off_maps_to_low_effort_for_harmony():
    tokens = _with("off", "")
    try:
        p = {"think": "low"}
        apply_to_ollama_native(p, "gpt-oss:20b")
        assert p["think"] == "low"  # never False for harmony
    finally:
        reset_overrides(tokens)


def test_on_requests_thinking_without_clobbering():
    tokens = _with("on", "")
    try:
        p = {}
        apply_to_ollama_native(p, "qwen3.5:9b")
        assert p["think"] is True
        p2 = {"think": "low"}
        apply_to_ollama_native(p2, "qwen3.5:9b")
        assert p2["think"] == "low"  # setdefault semantics
    finally:
        reset_overrides(tokens)


def test_effort_override_for_harmony_native_and_compat():
    tokens = _with("", "high")
    try:
        p = {"think": "low"}
        apply_to_ollama_native(p, "gpt-oss:20b")
        assert p["think"] == "high"
        assert effort_override() == "high"
    finally:
        reset_overrides(tokens)


def test_reset_restores_defaults():
    tokens = _with("off", "medium")
    reset_overrides(tokens)
    p = {}
    apply_to_ollama_native(p, "gemma4:12b")
    assert p == {}
    assert effort_override() == ""
