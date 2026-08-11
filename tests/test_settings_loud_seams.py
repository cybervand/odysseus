"""Tests for doc 021 phase 1: the settings route refuses unknown keys.

Before this change, the route dropped unknown keys and gave no error.
A write with a wrong key name failed with no signal. That silent drop
kept a dead control in the UI for days.
"""

from pathlib import Path

from src.settings import DEFAULT_SETTINGS, split_settings_update


def test_split_keeps_known_keys():
    known, unknown = split_settings_update({"agent_verifier_subagent": True})
    assert known == {"agent_verifier_subagent": True}
    assert unknown == []


def test_split_names_unknown_keys():
    known, unknown = split_settings_update(
        {"agent_verifier_subagent": True, "not_a_real_key": 1, "also_bad": 2}
    )
    assert known == {"agent_verifier_subagent": True}
    assert unknown == ["also_bad", "not_a_real_key"]


def test_split_accepts_every_registered_key():
    body = {k: v for k, v in DEFAULT_SETTINGS.items()}
    known, unknown = split_settings_update(body)
    assert unknown == []
    assert set(known) == set(DEFAULT_SETTINGS)


def test_split_empty_body_is_a_no_op():
    known, unknown = split_settings_update({})
    assert known == {}
    assert unknown == []


def test_route_refuses_unknown_keys():
    """The route must call the split and raise 400 for unknown keys."""
    src = Path("routes/auth_routes.py").read_text(encoding="utf-8")
    assert "_split_settings_update(body)" in src
    assert "Unknown settings keys" in src


def test_fork_ui_shows_write_failures():
    """The verifier switch must show a message when a save fails.

    The switch moved to a fork module (doc 021, phase 2)."""
    fork_js = Path("static/js/fork/commandMenu.js").read_text(encoding="utf-8")
    assert "Verifier setting not saved" in fork_js
    assert "Could not read the verifier setting" in fork_js