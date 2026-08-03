"""Document tools must report what changed: unified diff + added/removed counts.

Feeds three consumers at once: the chat tool card's +N/-M chip (same render
path as write_file diffs), the editor's change-highlighting, and the
completion verifier's actions snapshot — which previously judged edits
blind, false-rejecting real work and passing fabricated claims alike.
"""
from src.agent_tools.document_tools import _doc_diff
from src.agent_loop import _build_actions_snapshot


def test_doc_diff_shape_matches_file_diff_shape():
    d = _doc_diff("line one\nline two\n", "line one\nline 2\nline three\n", "fire_cube.frag")
    assert d is not None
    assert set(d) >= {"text", "added", "removed", "new_file"}
    assert d["added"] == 2 and d["removed"] == 1
    assert d["new_file"] is False
    assert "+line 2" in d["text"] and "-line two" in d["text"]


def test_doc_diff_none_when_unchanged_and_new_file_on_create():
    assert _doc_diff("same", "same", "t") is None
    d = _doc_diff("", "a\nb\n", "new doc")
    assert d["new_file"] is True and d["added"] == 2


def test_verifier_snapshot_includes_diff():
    events = [{
        "tool": "edit_document",
        "command": "DOC: abc",
        "output": "applied 1",
        "exit_code": None,
        "diff": {"text": "--- a/x\n+++ b/x\n@@\n-old line\n+new smoke line", "added": 1, "removed": 1},
    }]
    snap = _build_actions_snapshot(events)
    assert "+new smoke line" in snap
    assert "+1 -1" in snap


def test_verifier_snapshot_without_diff_unchanged():
    events = [{"tool": "bash", "command": "echo hi", "output": "hi", "exit_code": 0}]
    snap = _build_actions_snapshot(events)
    assert "diff applied" not in snap
    assert "[bash] echo hi" in snap
