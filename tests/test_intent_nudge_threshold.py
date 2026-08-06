"""Intent-without-action nudge: trailing promises stall at any length.

qwen3-coder (2026-08-06, morning after) ended a turn with a 428-character
pure announcement — "I'll search for appropriate images... Let me start by
searching..." — zero tool calls. The old <400-char gate missed it by 28
characters and the loop accepted the narration as a final answer. A response
that ENDS on an intent phrase is now a stall regardless of length; fenced
code anywhere still means a real answer.
"""
import re

import src.agent_loop as al

# The verbatim specimen (428 chars of sincere intention, zero action).
QWEN_SPECIMEN = (
    "I'll search for appropriate images from Wikimedia Commons for each "
    "drink and then fix the milkshake image issue. Let me start by "
    "searching for specific drinks on Wikimedia Commons to find suitable "
    "images that I can verify with curl before adding them to our menu. "
    "This will ensure each drink gets a fitting, working image and the "
    "milkshake no longer shows a pizza. Let me search for the espresso "
    "image first to get started on this."
)


def _promise_logic(text: str) -> bool:
    """Mirror of the loop's _looks_like_promise composition (guide_only False)."""
    m = al._INTENT_RE.search(text) if text else None
    if m is None or "```" in text:
        return False
    last = None
    for _m in al._INTENT_RE.finditer(text):
        last = _m
    ends_on_promise = last is not None and last.end() >= len(text) - 200
    return len(text) < 400 or ends_on_promise


def test_qwen_specimen_over_400_chars_still_nudges():
    assert len(QWEN_SPECIMEN) > 400  # the whole point
    assert _promise_logic(QWEN_SPECIMEN)


def test_short_promise_still_nudges():
    assert _promise_logic("Let me check the logs to see what happened.")


def test_long_answer_with_early_intent_not_nudged():
    text = (
        "I'll check the config first. "
        + ("The analysis shows the setting is correct. " * 30)
        + "In conclusion, everything is configured properly and no further "
        "changes are needed at this time. The system is healthy."
    )
    assert len(text) > 400
    assert not _promise_logic(text)


def test_fenced_code_means_real_answer():
    text = "Let me run the build:\n```bash\nnpm run build\n```\nDone above."
    assert not _promise_logic(text)


def test_long_answer_ending_on_promise_nudges():
    text = (
        ("Here is the full background of the situation. " * 20)
        + "Let me search for the correct image now."
    )
    assert len(text) > 400
    assert _promise_logic(text)
