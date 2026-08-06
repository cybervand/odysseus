"""Native-channel reasoning: persistence + the content-mute stall (2026-08-06).

A 232KB gemma4 run persisted as the 5-char reply "Done." — its reasoning
lived in the native thinking field (never in content), so history lost it,
and its final plan lived in the reasoning channel where the intent
supervisor couldn't see it. Two fixes, both pinned here:
- _merge_reasoning_for_persist: round_texts get a <think> block; the
  conversational text stays bare (echoed reasoning reinforces looping).
- _reasoning_channel_intent: a bare-closer reply with a reasoning tail
  ending on an intent phrase is the same unfinished-promise stall.
"""
from src.agent_loop import (
    _INTENT_RE,
    _merge_reasoning_for_persist,
    _reasoning_channel_intent,
)


# ── Persistence merge ──


def test_reasoning_merged_as_think_block():
    out = _merge_reasoning_for_persist("Done.", "The user wants a lodge site. Plan: templates first.")
    assert out.startswith("<think>\n")
    assert "Plan: templates first." in out
    assert out.endswith("</think>\n\nDone.")


def test_tag_models_not_double_wrapped():
    tagged = "<think>already inline</think>\n\nThe answer."
    assert _merge_reasoning_for_persist(tagged, "duplicate reasoning") == tagged


def test_no_reasoning_passthrough():
    assert _merge_reasoning_for_persist("A normal reply.", "") == "A normal reply."


def test_reasoning_with_empty_reply_still_persists():
    out = _merge_reasoning_for_persist("", "thought about it, concluded nothing to say")
    assert out.startswith("<think>") and out.endswith("</think>")


# ── Content-mute stall detection ──

_STALLED_REASONING = (
    "I've completed step 1 and part of step 2. Now I need to finish the "
    "templates, then perform step 3 with image receipts, then start the "
    "server with manage_server. Let me start with creating more templates."
)


def test_bare_closer_with_planning_tail_is_a_stall():
    m, text = _reasoning_channel_intent("Done.", _STALLED_REASONING, _INTENT_RE)
    assert m is not None
    assert "Let me start" in m.group(0) or "Let me" in m.group(0)
    assert text != "Done."          # supervisor now scans the reasoning tail


def test_substantive_reply_is_not_a_stall():
    reply = ("I finished the data.json and all templates. The server is running "
             "on port 8090 and verified with curl. " * 3)
    m, text = _reasoning_channel_intent(reply, _STALLED_REASONING, _INTENT_RE)
    assert m is None and text == reply


def test_reasoning_that_concludes_is_not_a_stall():
    concluded = ("I considered adding more templates but everything required "
                 "is complete and verified. The task is done.")
    m, _ = _reasoning_channel_intent("Done.", concluded, _INTENT_RE)
    assert m is None


def test_intent_buried_mid_reasoning_is_not_a_stall():
    buried = ("Let me check the files first. " + "I verified everything works as expected. " * 12)
    m, _ = _reasoning_channel_intent("Done.", buried, _INTENT_RE)
    assert m is None                 # intent must be at the TAIL


def test_code_fence_reply_is_not_a_stall():
    m, _ = _reasoning_channel_intent("```py\nprint(1)\n```", _STALLED_REASONING, _INTENT_RE)
    assert m is None
