"""Doc 016 companion fix: recovered_partial saves stop bypassing the
thinking extractor, and the extractor handles multi-block content.

The corpus shape: a checkpoint is "\n\n".join(round_texts) where each round
(post _merge_reasoning_for_persist) opens with its own <think> block —
session 9bdad2b1 shipped two such rows raw (35,710 and 32,094 chars, 16
paired blocks). Fixtures here are that shape in miniature.
"""
import pytest

from routes.chat_helpers import _collect_think_blocks, _extract_thinking_meta, clean_thinking_for_save
from src.run_checkpoint import promote_if_orphaned, write_partial, clear_partial


TWO_ROUNDS = (
    "<think>\nplan the backend first\n</think>\n\n"
    "Writing app.py now.\n\n"
    "<think>\nnow the frontend templates\n</think>\n\n"
    "Done."
)


def _many_rounds(n):
    return "\n\n".join(
        f"<think>\nround {i} reasoning\n</think>\n\nround {i} talk."
        for i in range(1, n + 1)
    )


class TestCollectThinkBlocks:
    def test_two_blocks_join_with_separator(self):
        thinking, residue = _collect_think_blocks(TWO_ROUNDS)
        assert "plan the backend first" in thinking
        assert "now the frontend templates" in thinking
        assert "---" in thinking
        assert residue == "Writing app.py now.\n\nDone."

    def test_sixteen_blocks_all_extracted(self):
        thinking, residue = _collect_think_blocks(_many_rounds(16))
        assert thinking.count("---") == 15
        assert "<think>" not in residue
        for i in (1, 8, 16):
            assert f"round {i} reasoning" in thinking
            assert f"round {i} talk." in residue

    def test_trailing_unclosed_block_is_thinking(self):
        text = "<think>\ndone thinking\n</think>\n\nsome talk\n\n<think>\nkilled mid-thou"
        thinking, residue = _collect_think_blocks(text)
        assert "killed mid-thou" in thinking
        assert residue == "some talk"


class TestExtractThinkingMetaMultiBlock:
    def test_multi_block_yields_one_thinking_and_clean_reply(self):
        info = _extract_thinking_meta(TWO_ROUNDS)
        assert info is not None
        assert "plan the backend first" in info["thinking"]
        assert "now the frontend templates" in info["thinking"]
        assert "<think>" not in info["reply"]
        assert "Writing app.py now." in info["reply"]
        assert info["reply"].endswith("Done.")

    def test_single_leading_block_behavior_unchanged(self):
        info = _extract_thinking_meta("<think>\nonly thoughts\n</think>\n\nThe answer.")
        assert info == {"thinking": "only thoughts", "reply": "The answer.", "time": None}

    def test_mid_text_think_without_leading_block_untouched(self):
        # A message QUOTING think tags (e.g. our own debugging chats) must
        # not be mangled — the multi-block path is anchored to a leading block.
        text = "Here is what the model emitted:\n\n<think>\nquoted\n</think>\n\nweird, right?"
        assert _extract_thinking_meta(text) is None

    def test_reasoning_only_multiblock_returns_none(self):
        # No talk at all -> keep raw content (blank-bubble guard).
        text = "<think>\nround 1\n</think>\n\n<think>\nround 2\n</think>"
        assert _extract_thinking_meta(text) is None


class _FakeSessionManager:
    def __init__(self):
        self.saved = []

    def add_message(self, session_id, msg):
        self.saved.append((session_id, msg))


class TestPromoteIfOrphaned:
    SID = "test-promote-thinking-x1"

    def teardown_method(self):
        clear_partial(self.SID)

    def test_promoted_row_is_clean_with_thinking_in_metadata(self):
        write_partial(self.SID, TWO_ROUNDS, 2)
        mgr = _FakeSessionManager()
        assert promote_if_orphaned(self.SID, mgr, "dead") is True
        (sid, msg), = mgr.saved
        assert sid == self.SID
        assert "<think>" not in msg.content
        assert "Writing app.py now." in msg.content
        assert "*[recovered" in msg.content
        assert msg.metadata["recovered_partial"] is True
        assert msg.metadata["rounds"] == 2
        assert "plan the backend first" in msg.metadata["thinking"]
        assert "now the frontend templates" in msg.metadata["thinking"]

    def test_reasoning_only_checkpoint_keeps_raw_text(self):
        raw = "<think>\nonly ever thought\n</think>"
        write_partial(self.SID, raw, 1)
        mgr = _FakeSessionManager()
        assert promote_if_orphaned(self.SID, mgr, "dead") is True
        (_, msg), = mgr.saved
        assert raw in msg.content            # renderer extracts visually
        assert "thinking" not in msg.metadata

    def test_running_run_never_promotes(self):
        write_partial(self.SID, TWO_ROUNDS, 2)
        mgr = _FakeSessionManager()
        assert promote_if_orphaned(self.SID, mgr, "running") is False
        assert mgr.saved == []


class TestCleanThinkingForSave:
    def test_multiblock_content_metadata_merge(self):
        content, md = clean_thinking_for_save(TWO_ROUNDS, {"model": "gemma4"})
        assert "<think>" not in content
        assert md["model"] == "gemma4"
        assert "plan the backend first" in md["thinking"]
