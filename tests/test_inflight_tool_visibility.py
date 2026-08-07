"""In-flight tool visibility (doc 008): a RUNNING tool call must be
queryable — logs only recorded completions, so a blocking server launch
held a run hostage for 10 minutes with zero server-side trace (2026-08-06,
twice)."""
import asyncio
import importlib

import pytest


@pytest.mark.anyio
async def test_list_runs_carries_current_tool_while_executing():
    # Resolve modules at RUNTIME, not collection: an earlier test reloading
    # src.tool_execution would otherwise split identities — this test would
    # patch/write the OLD module while list_runs lazily imports the NEW one,
    # and current_tool never appears (failed in full-suite runs on both
    # Windows and Linux while passing standalone, 2026-08-07).
    ar = importlib.import_module("src.agent_runs")
    te = importlib.import_module("src.tool_execution")
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowBlock:
        tool_type = "bash"
        content = "python app.py"

    async def _fake_impl(block, **kw):
        started.set()
        await release.wait()
        return ("bash", {"output": "done", "exit_code": 0})

    orig = te._execute_tool_block_impl
    te._execute_tool_block_impl = _fake_impl
    try:
        async def agen():
            yield "data: x\n\n"
            await te.execute_tool_block(SlowBlock(), session_id="inflight-test")
            yield "data: y\n\n"

        run = ar.start("inflight-test", agen())
        await asyncio.wait_for(started.wait(), timeout=5)
        # list_runs is a monitoring API — its contract is visibility within
        # a moment, not at an exact interleaving. Under full-suite load this
        # raced rarely on BOTH Windows and Linux (KeyError: current_tool),
        # so poll briefly instead of asserting the first snapshot.
        entry = {}
        for _ in range(50):
            entry = next(r for r in ar.list_runs() if r["session_id"] == "inflight-test")
            if "current_tool" in entry:
                break
            await asyncio.sleep(0.02)
        assert entry["current_tool"] == "bash"
        assert "python app.py" in entry["tool_args_head"]
        assert entry["tool_running_s"] >= 0
        release.set()
        await asyncio.wait_for(run.task, timeout=5)
        entry2 = next(r for r in ar.list_runs() if r["session_id"] == "inflight-test")
        assert "current_tool" not in entry2   # cleared after completion
    finally:
        te._execute_tool_block_impl = orig
        ar._RUNS.pop("inflight-test", None)
        te._INFLIGHT.pop("inflight-test", None)
