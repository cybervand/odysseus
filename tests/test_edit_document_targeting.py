"""edit_document must be able to edit the document the model actually means.

Live failure: qwen read "Cube Shader Pair" via manage_documents, built
correct FIND text from it — and edit_document applied the edit to a
different document entirely (the process-global active-doc pointer /
most-recently-updated fallback), reporting "none of the FIND blocks
matched". The model had no way to name its target.

Fixes under test: the `DOC: <id-or-title>` header (and document_id arg in
the native schema, converted to that header), the retarget-on-miss scan
when exactly one owned document matches, and an actionable error that
names the document that was actually targeted.
"""
import json

import src.agent_tools.document_tools as dt
from src.tool_schemas import function_call_to_tool_block


BLOCKS = "<<<FIND>>>\nold text\n<<<REPLACE>>>\nnew text\n<<<END>>>"


def test_native_document_id_arg_becomes_doc_header():
    block = function_call_to_tool_block("edit_document", json.dumps({
        "document_id": "abc-123",
        "edits": [{"find": "old text", "replace": "new text"}],
    }))
    assert block is not None
    assert block.content.startswith("DOC: abc-123\n<<<FIND>>>")
    ref, rest = dt.extract_edit_target(block.content)
    assert ref == "abc-123"
    assert dt.parse_edit_blocks(rest) == [{"find": "old text", "replace": "new text"}]


def test_extract_target_header_forms():
    for header in ("DOC: abc-123", "doc: abc-123", "DOCUMENT_ID: abc-123", "document: abc-123"):
        ref, rest = dt.extract_edit_target(f"{header}\n{BLOCKS}")
        assert ref == "abc-123", header
        assert rest == BLOCKS


def test_no_header_passes_through_unchanged():
    ref, rest = dt.extract_edit_target(BLOCKS)
    assert ref is None
    assert rest == BLOCKS


def test_find_block_on_first_line_is_not_a_target():
    ref, rest = dt.extract_edit_target("<<<FIND>>>\nDOC: not a header\n<<<REPLACE>>>\nx\n<<<END>>>")
    assert ref is None


def test_apply_edits_exact_and_gutter_fallback():
    text = "line one\nline two\n"
    updated, applied, skipped = dt._apply_edits(text, [{"find": "line two", "replace": "line 2"}])
    assert (applied, skipped) == (1, 0) and "line 2" in updated
    # Gutter-prefixed FIND still matches the clean document.
    updated, applied, skipped = dt._apply_edits(text, [{"find": "2\tline two", "replace": "line 2"}])
    assert (applied, skipped) == (1, 0) and "line 2" in updated
    # A genuine miss is a skip, not silent success.
    updated, applied, skipped = dt._apply_edits(text, [{"find": "absent", "replace": "x"}])
    assert (applied, skipped) == (0, 1) and updated == text
