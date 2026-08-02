"""Verifier empty-response handling.

The completion verifier fails open by design (a broken verifier must not
block a valid completion) — but reasoning models can spend the whole
900-token budget in their thinking channel and return empty content, which
the fail-open default silently converts into a PASS. Caught live: gpt-oss
fabricated "the poems have been written", the gpt-oss verifier returned
empty, the claim sailed through.

The fix: retry once at a bigger budget (which also changes the
llm_call_async cache key — an identical retry would replay the cached
empty string), and warn loudly before failing open.
"""
import asyncio

import src.agent_loop as agent_loop
import src.llm_core as llm_core


def _run_verifier():
    return asyncio.run(agent_loop._run_verifier_subagent(
        "write a haiku to /tmp/x.txt",
        "tool: python -> exit 0",
        endpoint_url="http://fake:1/v1", model="gpt-oss:20b", headers={},
    ))


def test_empty_then_verdict_retries_with_bigger_budget(monkeypatch):
    calls = []

    async def fake_llm(url, model, messages, **kw):
        calls.append(kw.get("max_tokens"))
        if len(calls) == 1:
            return ""
        return "1. UNMET no file written\nVERIFICATION: FAIL: file never written"

    monkeypatch.setattr(llm_core, "llm_call_async", fake_llm)
    failures = _run_verifier()
    assert calls == [900, 1600]
    assert failures and "no file written" in failures[0]


def test_first_answer_skips_retry(monkeypatch):
    calls = []

    async def fake_llm(url, model, messages, **kw):
        calls.append(kw.get("max_tokens"))
        return "VERIFICATION: SUCCESS"

    monkeypatch.setattr(llm_core, "llm_call_async", fake_llm)
    assert _run_verifier() == []
    assert calls == [900]


def test_empty_twice_fails_open_with_warning(monkeypatch, caplog):
    async def fake_llm(url, model, messages, **kw):
        return ""

    monkeypatch.setattr(llm_core, "llm_call_async", fake_llm)
    with caplog.at_level("WARNING"):
        failures = _run_verifier()
    assert failures == []  # fail-open preserved
    assert any("empty" in r.message for r in caplog.records)
