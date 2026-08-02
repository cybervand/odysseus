"""The python tool must see pip-installed packages.

It previously ran `python -I` (isolated mode), which disables user
site-packages — but pip installs from the bash tool land exactly there
(non-root pip auto-falls-back to --user). Result: `pip install X` reports
success, `import X` through the python tool fails forever, and agents burn
their whole round budget fighting an unsatisfiable environment. Measured:
4 of 5 gpt-oss completion-validation runs died in that loop.

These tests execute the real interpreter the way the tool does and assert
the isolation flags are actually off — not just that "-I" is absent.
"""
import asyncio

import pytest

import src.tool_execution as tool_execution
from src.agent_tools.subprocess_tools import PythonTool


@pytest.fixture(autouse=True)
def _stable_cwd(monkeypatch, tmp_path):
    # Other suite tests can leave the active workspace pointing at a deleted
    # temp dir; agent_cwd() then makes subprocess spawn fail. Pin it.
    monkeypatch.setattr(tool_execution, "agent_cwd", lambda: str(tmp_path))


def _run(code: str) -> dict:
    return asyncio.run(PythonTool().execute(code, {"progress_cb": None, "subproc_env": None}))


def test_python_tool_is_not_isolated():
    res = _run("import sys; print(sys.flags.isolated, sys.flags.no_user_site)")
    assert res.get("exit_code") == 0, res
    assert res["output"].strip() == "0 0"


def test_python_tool_sees_user_site_packages():
    # site.getusersitepackages() must be on sys.path when the dir exists —
    # in isolated mode it never is, regardless of existence. ENABLE_USER_SITE
    # False/None means the interpreter refuses user site: the -I regression.
    res = _run("import site; print(site.ENABLE_USER_SITE)")
    assert res.get("exit_code") == 0, res
    assert res["output"].strip() == "True"
