"""Run discovery for live observation (design doc 008).

A watcher needs to find running sessions before it can attach to their
replay+live feed via /api/chat/resume — list_runs is that discovery.
"""
import src.agent_runs as agent_runs


def _fake_run(status="running", events=0, subs=0):
    r = agent_runs._Run()
    r.status = status
    r.buffer = [f"ev{i}" for i in range(events)]
    r.subscribers = set(range(subs))
    return r


def test_list_runs_reports_status_and_counts(monkeypatch):
    monkeypatch.setattr(agent_runs, "_RUNS", {
        "sess-a": _fake_run("running", events=7, subs=1),
        "sess-b": _fake_run("done", events=42),
    })
    runs = {r["session_id"]: r for r in agent_runs.list_runs()}
    assert runs["sess-a"]["status"] == "running"
    assert runs["sess-a"]["events"] == 7
    assert runs["sess-a"]["subscribers"] == 1
    assert runs["sess-b"]["status"] == "done"
    assert runs["sess-b"]["events"] == 42


def test_list_runs_empty():
    orig = agent_runs._RUNS
    try:
        agent_runs._RUNS = {}
        assert agent_runs.list_runs() == []
    finally:
        agent_runs._RUNS = orig
