"""Qwen3-Coder's <function=...> tool-call dialect must parse, execute, and strip.

Qwen3-Coder's chat template formats tool calls as

    <function=bash>
    <parameter=command>
    ls /app
    </parameter>
    </function>

and this leaks into message content as plain text whenever the serving layer
fails to turn it into structured tool_calls (observed live from
qwen3-coder:30b via Ollama's /v1 endpoint: the agent announced its plan,
emitted <function=manage_documents> as text, and the turn ended with nothing
executed). Explicit call markup is never illustrative, so it must parse into
real ToolBlocks — and be stripped from the displayed text like every other
leaked dialect.
"""
import src.agent_loop as al
from src.tool_parsing import parse_tool_blocks, strip_tool_blocks


QWEN_BASH = """I'll list the directory first.

<function=bash>
<parameter=command>
ls -la /app/data
</parameter>
</function>"""


def test_qwen_function_dialect_parses_to_tool_block():
    blocks = parse_tool_blocks(QWEN_BASH, skip_fenced=True)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"
    assert "ls -la /app/data" in blocks[0].content


def test_qwen_function_dialect_multi_parameter():
    text = """<function=write_file>
<parameter=path>
/app/data/health/x.txt
</parameter>
<parameter=content>
hello
</parameter>
</function>"""
    blocks = parse_tool_blocks(text, skip_fenced=True)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "write_file"


def test_live_failure_shape_manage_documents_executes():
    # The exact shape from the stranded run: prose + <function=manage_documents>.
    text = """I'll build a stack health check tool for your AI server step by step.

<function=manage_documents>
<parameter=action>
list
</parameter>
</function>"""
    blocks = parse_tool_blocks(text, skip_fenced=True)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "manage_documents"


def test_unknown_tool_name_in_dialect_yields_no_block():
    text = "<function=cat>\n<parameter=file_path>\n/tmp/x\n</parameter>\n</function>"
    assert parse_tool_blocks(text, skip_fenced=True) == []


def test_dialect_is_stripped_from_display_text():
    cleaned = strip_tool_blocks(QWEN_BASH, skip_fenced=True)
    assert "<function=" not in cleaned
    assert "<parameter=" not in cleaned
    assert "I'll list the directory first." in cleaned


def test_resolve_tool_blocks_executes_dialect_for_native_models():
    # End-to-end through the agent loop's resolver: a native-tools model with
    # zero native calls but leaked Qwen markup must still produce a real block.
    blocks, used_native, converted, failed, _ = al._resolve_tool_blocks(
        QWEN_BASH, [], round_num=1, is_api_model=True
    )
    assert used_native is False
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"
