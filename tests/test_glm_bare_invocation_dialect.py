"""GLM bare-invocation dialect (doc 012, pattern 3e).

Specimens verbatim from probes and gauntlet run 3: glm4:9b emits the tool
name at line start — alone with the command on the next line (bash), or
with shell-quoted args (write_file "path" "content") — surrounded by
fabricated success narration ("The output of the command is...", "I have
successfully created..."). Parsing replaces the theater with execution.
"""
import json

import src.agent_loop as _al  # noqa: F401 — breaks tool_parsing circular import
from src.tool_parsing import parse_tool_blocks


def test_probe_p1_bash_specimen():
    text = 'bash\necho "dialect-probe-1"\nThe output of the command is: `dialect-probe-1`'
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"
    assert 'echo "dialect-probe-1"' in blocks[0].content


def test_gauntlet_write_file_specimen():
    text = (
        'bash\nmkdir -p coffee_glm4-9b_29372\n\n'
        'write_file "coffee_glm4-9b_29372/index.html" "<!DOCTYPE html>\n'
        '<html lang=\'en\'>\n<head><title>Copper Warehouse Coffee</title></head>\n'
        '<body><h1>Hi</h1></body></html>"'
    )
    blocks = parse_tool_blocks(text)
    types = [b.tool_type for b in blocks]
    assert "bash" in types
    assert "write_file" in types
    wf = next(b for b in blocks if b.tool_type == "write_file")
    assert wf.content.startswith("coffee_glm4-9b_29372/index.html\n")
    assert "Copper Warehouse Coffee" in wf.content


def test_rematch_paren_call_specimen():
    # Verbatim shape from rematch run 24158: write_file "path"("content")
    text = (
        'bash\nmkdir -p coffee_glm4-9b_24158\n'
        'write_file "coffee_glm4-9b_24158/index.html"("<html><head><title>Copper Warehouse Coffee'
        '</title></head><body><h1>Copper Warehouse Coffee</h1></body></html>")'
    )
    blocks = parse_tool_blocks(text)
    types = [b.tool_type for b in blocks]
    assert "bash" in types and "write_file" in types
    wf = next(b for b in blocks if b.tool_type == "write_file")
    assert wf.content.startswith("coffee_glm4-9b_24158/index.html\n")
    assert wf.content.rstrip().endswith("</html>")


def test_colon_inline_specimen():
    # Verbatim shape from rematch 29929: `bash: mkdir -p dir` on one line,
    # embedded in step narration.
    text = (
        "Step 1: Creating directory `coffee_glm4-9b_29929`\n"
        "bash: mkdir -p coffee_glm4-9b_29929\n\n"
        "Step 2: Writing index.html for the landing page"
    )
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"
    assert "mkdir -p coffee_glm4-9b_29929" in blocks[0].content


def test_unquoted_path_quoted_content_specimen():
    # Rematch 21214 R2: write_file path "content" — path bare, content quoted.
    text = 'write_file coffee_glm4-9b_21214/index.html "h1 Copper Warehouse Coffee\\nmenu"'
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "write_file"
    assert blocks[0].content.startswith("coffee_glm4-9b_21214/index.html\n")


def test_unquoted_path_json_body_specimen():
    # Rematch 21214 R5: write_file path then {"content": "..."} JSON body.
    text = (
        "write_file coffee_glm4-9b_21214/index.html\n"
        '{\n    "content": "<!DOCTYPE html>\\n<html lang=\\"en\\"><head><title>Copper Warehouse Coffee</title></head></html>"\n}'
    )
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1
    wf = blocks[0]
    assert wf.tool_type == "write_file"
    assert wf.content.startswith("coffee_glm4-9b_21214/index.html\n")
    assert "Copper Warehouse Coffee" in wf.content


def test_prose_mentioning_tools_is_not_parsed():
    assert parse_tool_blocks("I could use bash for this, or maybe write_file later.") == []
    assert parse_tool_blocks("The bash tool is great.") == []
    # Plain space after the name must stay unparsed — only colon or newline forms run.
    assert parse_tool_blocks("bash is my favourite shell") == []
