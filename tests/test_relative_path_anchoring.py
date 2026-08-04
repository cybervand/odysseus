"""Relative paths must mean the same place in every tool.

Live failure: in a no-workspace session, bash ran `mkdir -p
hammer-hub/frontend` (subprocess cwd = agent_cwd = data dir), then the ls
TOOL rejected the identical relative path as "outside the allowed roots" —
_resolve_tool_path realpath'd it against the server process cwd instead.
The model concluded it needed a workspace and stopped to ask the user.
"""
import os

import pytest

import src.tool_execution as te


@pytest.fixture
def _anchored(monkeypatch, tmp_path):
    root = os.path.realpath(str(tmp_path))
    monkeypatch.setattr(te, "_AGENT_WORKDIR", root)
    monkeypatch.setattr(te, "_tool_path_roots", lambda: [root])
    # No workspace bound — the branch under test.
    token = te._active_workspace.set(None)
    yield root
    te._active_workspace.reset(token)


def test_relative_path_resolves_under_agent_cwd(_anchored):
    resolved = te._resolve_tool_path("hammer-hub/frontend")
    assert resolved == os.path.realpath(os.path.join(_anchored, "hammer-hub/frontend"))


def test_relative_path_matches_bash_cwd(_anchored):
    # The invariant that broke: file tools and bash agree on what "." means.
    assert os.path.realpath(te.agent_cwd()) == _anchored
    assert te._resolve_tool_path("x.txt").startswith(_anchored)


def test_absolute_paths_still_confined(_anchored):
    outside = os.path.realpath(os.path.join(_anchored, "..", "elsewhere.txt"))
    with pytest.raises(ValueError):
        te._resolve_tool_path(outside)


def test_relative_escape_is_still_caught(_anchored):
    with pytest.raises(ValueError):
        te._resolve_tool_path("../../etc/passwd")
