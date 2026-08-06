"""In-flight tool visibility (doc 008): a RUNNING tool call must be
queryable — logs only recorded completions, so a blocking server launch
held a run hostage for 10 minutes with zero server-side trace (2026-08-06,
twice)."""
import asyncio

import pytest

import src.agent_runs as ar
import src.tool_execution as te


@pytest.mark.anyio
async def test_list_runs_carries_current_tool_while_executing():
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
        entry = next(r for r in ar.list_runs() if r["session_id"] == "inflight-test")
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
