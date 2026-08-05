"""Web-intent strip guards + policy source attribution (doc 008).

The night of 2026-08-05: a user asked gpt-oss to build a website whose brief
mentioned "images from the net"; the web-intent regex stripped bash and every
file tool; the model truthfully said it had no shell mid-build. The strip now
skips command-signaling turns and explicit bash grants; every disabled tool
carries a `source` naming its gate; the policy log no longer truncates.
"""
import pathlib
import re

import src.agent_loop as al
from src.tool_policy import build_effective_tool_policy

import routes.chat_routes as cr

_CHAT_ROUTES = pathlib.Path(cr.__file__)
_AGENT_LOOP = pathlib.Path(al.__file__)

# The message shape that caused the failure: webby words AND command words.
TONIGHTS_MESSAGE = (
    "Build me a website and serve it locally - grab a few placeholder "
    "images from the web for the gallery"
)
PURE_WEB_MESSAGE = "what's the weather in Oslo today?"


# ── The two real classifiers, on the real inputs ──


def test_tonights_message_trips_both_classifiers():
    assert cr._EXPLICIT_WEB_INTENT_RE.search(TONIGHTS_MESSAGE.lower())
    assert al._message_signals_commands(TONIGHTS_MESSAGE)


def test_pure_web_message_has_no_command_signal():
    assert cr._EXPLICIT_WEB_INTENT_RE.search(PURE_WEB_MESSAGE.lower())
    assert not al._message_signals_commands(PURE_WEB_MESSAGE)


def test_original_gauntlet_r0_prompt_signals_commands():
    # The ladder R0 ("...make it with react vite...") must never be disarmed.
    r0 = (
        "build me a website for my local business, i want to have it pretty "
        "its for a company called Kaffe on the Moors so i want you to get "
        "open source images from the net, i also want you make it with react vite"
    )
    assert al._message_signals_commands(r0)


# ── Structural pins on the gate logic (the guard must not silently vanish) ──


def test_web_intent_strip_guarded_by_command_signal():
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    assert "_command_signals = _message_signals_commands(message)" in source
    assert "_bash_explicitly_granted = tool_toggle_enabled(allow_bash)" in source
    # The strip runs only when the message does NOT signal commands…
    assert "if not _command_signals:" in source
    # …and shell/file tools are only included without an explicit grant.
    assert "if not _bash_explicitly_granted:" in source
    assert '_disable(_web_intent_strip, "web-intent")' in source


def test_escalation_strip_has_same_escape_hatch():
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    assert "if auto_escalated and not _workspace_agent_intent:" in source
    assert (
        "if not ((_web_intent_escalation and _command_signals) or _bash_explicitly_granted):"
        in source
    )


def test_policy_log_no_longer_truncates():
    source = _AGENT_LOOP.read_text(encoding="utf-8")
    assert "['disabled'][:12]" not in source
    assert "disabled_n=" in source and "by_gate=" in source


# ── Source attribution through the real policy builder ──


def test_sources_flow_through_policy():
    policy = build_effective_tool_policy(
        disabled_tools={"bash", "web_search"},
        last_user_message="normal request",
        disabled_sources={"bash": "route-toggle"},
    )
    assert policy.sources["bash"] == "route-toggle"
    assert policy.sources["web_search"] == "route"  # unattributed default


def test_guide_only_still_strips_everything_and_attributes():
    policy = build_effective_tool_policy(
        disabled_tools=set(),
        last_user_message="do not use any tools; run npm install",
    )
    assert policy.block_all_tool_calls
    assert policy.mode == "guide_only"
    assert "bash" in policy.all_disabled_names()
    assert policy.sources.get("bash") == "guide-only"


def test_explicit_bash_grant_is_a_summons_not_a_permission_slip():
    """The toggle the user turned ON must put bash in the round's toolbox
    regardless of what the relevance filter thinks the message sounds like
    (gate #4: terminal=False with disabled_n=0)."""
    source = _CHAT_ROUTES.read_text(encoding="utf-8")
    assert 'if _bash_explicitly_granted and "bash" not in disabled_tools:' in source
    assert "_forced_tools = (_forced_tools or set()) | {" in source


def test_positional_toolpolicy_construction_still_works():
    # `sources` was appended LAST on the frozen dataclass precisely so older
    # positional constructions keep working.
    from src.tool_policy import ToolPolicy
    p = ToolPolicy(frozenset({"bash"}), frozenset(), {}, "normal", False, False)
    assert p.sources == {}
