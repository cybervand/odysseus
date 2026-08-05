"""write_file native calls must carry content — never silently write 0 bytes.

qwen R0 autopsy (doc 013): round 14 emitted a native write_file whose
content never arrived (renamed key or backend-dropped argument); the old
converter defaulted to "" and wrote an empty index.html — the site's fatal
defect — while the model was told nothing actionable. A content-less write
now fails conversion, which routes into the failed-call feedback the model
actually reads and retries on.
"""
import src.agent_loop as al  # noqa: F401 — breaks tool_parsing circular import
from src.tool_schemas import function_call_to_tool_block


def test_missing_content_rejected():
    assert function_call_to_tool_block("write_file", '{"path": "a.txt"}') is None


def test_empty_content_rejected():
    assert function_call_to_tool_block("write_file", '{"path": "a.txt", "content": ""}') is None


def test_normal_write_converts():
    b = function_call_to_tool_block("write_file", '{"path": "a.txt", "content": "hi"}')
    assert b is not None and b.tool_type == "write_file"
    assert b.content == "a.txt\nhi"


def test_content_aliases_accepted():
    for alias in ("contents", "text", "body", "file_content", "data"):
        b = function_call_to_tool_block("write_file", f'{{"path": "a.txt", "{alias}": "via-{alias}"}}')
        assert b is not None, alias
        assert b.content == f"a.txt\nvia-{alias}"


def test_structured_body_serialized():
    b = function_call_to_tool_block("write_file", '{"path": "a.json", "content": {"k": 1}}')
    assert b is not None
    assert b.content == 'a.json\n{"k": 1}'


def test_rejected_write_reaches_failed_call_feedback():
    native = [{"name": "write_file", "arguments": '{"path": "a.txt"}'}]
    blocks, used_native, _, failed, _ = al._resolve_tool_blocks("", native, 1)
    assert blocks == []
    assert not used_native
    assert failed and failed[0]["name"] == "write_file"
