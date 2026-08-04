"""llama3-JSON dialect: bare {"name": ..., "parameters": {...}} in content.

Gauntlet run 2 (doc 011) caught llama3.1:8b emitting a PERFECT tool call as
plain JSON text — valid name, valid args, real HTML payload — and scoring
zero because nothing parsed it. The dialect chain (doc 009) gains a bare-
JSON pattern; raw_decode brace-balancing means payloads containing braces
({} in CSS/JS) parse correctly.
"""
import json

import src.agent_loop as _al  # noqa: F401 — breaks the tool_parsing circular import
from src.tool_parsing import parse_tool_blocks


def test_bare_llama_json_call_parses():
    text = json.dumps({
        "name": "write_file",
        "parameters": {
            "path": "site/index.html",
            "content": "<style>body {background: #f0f0f0;}</style><h1>Hi</h1>",
        },
    })
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "write_file"
    assert "background: #f0f0f0" in blocks[0].content


def test_arguments_key_variant_and_surrounding_prose():
    text = 'I will create the file now.\n' + json.dumps({
        "name": "bash", "arguments": {"command": "mkdir -p site"}
    }) + "\nDone."
    blocks = parse_tool_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"


def test_unknown_tool_or_plain_json_ignored():
    assert parse_tool_blocks('{"name": "no_such_tool_xyz", "parameters": {"a": 1}}') == []
    assert parse_tool_blocks('{"name": "Peter", "age": 30}') == []
    assert parse_tool_blocks("just prose, no calls") == []
