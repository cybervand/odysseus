"""find_images: the images cliff, toolified (doc 013).

Five straight runs proved 30B models improvise around image PROCEDURES
(inventing URLs, scraping imaginary DOM, shipping known-404s) while
executing native tool calls faithfully. So the whole pipeline — Commons
API search + live HEAD verification — moved inside one tool. The model
asks for a subject; only URLs proven 200 come back.
"""
import asyncio
import json

import pytest

import src.agent_tools.web_tools as wt
from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS, function_call_to_tool_block


def test_registered_everywhere():
    assert "find_images" in TOOL_HANDLERS
    assert "find_images" in TOOL_TAGS
    names = [(s.get("function") or {}).get("name") for s in FUNCTION_TOOL_SCHEMAS]
    assert "find_images" in names


def test_native_call_converts():
    b = function_call_to_tool_block("find_images", '{"query": "ski slope", "count": 2}')
    assert b is not None and b.tool_type == "find_images"
    assert json.loads(b.content)["query"] == "ski slope"


def test_native_call_requires_query():
    assert function_call_to_tool_block("find_images", "{}") is None


@pytest.fixture()
def fake_pipeline(monkeypatch):
    calls = {}

    def _fake(self, query, count):
        calls["query"], calls["count"] = query, count
        return [{"title": f"File:{query}.jpg", "url": f"https://upload.wikimedia.org/x/{query}.jpg"}][:count]

    monkeypatch.setattr(wt.FindImagesTool, "_search_and_verify", _fake)
    return calls


def test_execute_json_args(fake_pipeline):
    r = asyncio.run(wt.FindImagesTool().execute('{"query": "mountain lodge winter"}', {}))
    assert r["exit_code"] == 0
    assert "VERIFIED 200:" in r["output"]
    assert fake_pipeline["query"] == "mountain lodge winter"


def test_execute_bare_string(fake_pipeline):
    r = asyncio.run(wt.FindImagesTool().execute("latte art", {}))
    assert r["exit_code"] == 0
    assert "latte art" in r["output"]


def test_empty_query_errors():
    r = asyncio.run(wt.FindImagesTool().execute("", {}))
    assert r["exit_code"] == 1


def test_no_results_is_honest(monkeypatch):
    monkeypatch.setattr(wt.FindImagesTool, "_search_and_verify", lambda self, q, c: [])
    r = asyncio.run(wt.FindImagesTool().execute("xyzzy nonsense", {}))
    assert r["exit_code"] == 1
    assert "no verified images" in r["error"]
