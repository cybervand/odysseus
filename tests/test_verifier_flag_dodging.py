"""A verifier flag must survive read-only tool rounds.

Live exploit (accidental, by gpt-oss): a failed edit_document got flagged
by the completion verifier; the model then ran two manage_documents READS,
which cleared `_verifier_fix_pending` (any tool round used to clear it);
its next message claimed the edits were applied — and with the flag gone
and no fresh effectful work, neither the accountability pushback nor a
re-verify fired. Fabricated completion, delivered to the user.

Rule under test: only effectful tools clear the flag.
"""
from types import SimpleNamespace

from src.agent_loop import _round_clears_verifier_flag, _VERIFIER_EFFECTFUL_TOOLS


def _blocks(*tool_types):
    return [SimpleNamespace(tool_type=t) for t in tool_types]


def test_read_only_rounds_do_not_clear_the_flag():
    assert _round_clears_verifier_flag(_blocks("manage_documents")) is False
    assert _round_clears_verifier_flag(_blocks("get_workspace", "read_file", "ls", "grep")) is False
    assert _round_clears_verifier_flag([]) is False
    assert _round_clears_verifier_flag(None) is False


def test_effectful_rounds_clear_the_flag():
    for tool in sorted(_VERIFIER_EFFECTFUL_TOOLS):
        assert _round_clears_verifier_flag(_blocks(tool)) is True, tool
    # Mixed round: one effectful call among reads still counts as fixing.
    assert _round_clears_verifier_flag(_blocks("read_file", "edit_document")) is True


def test_read_only_document_tools_are_not_considered_effectful():
    # manage_documents (list/read/delete) must never be in the effectful set —
    # adding it would reopen the flag-dodging hole this file guards.
    assert "manage_documents" not in _VERIFIER_EFFECTFUL_TOOLS
