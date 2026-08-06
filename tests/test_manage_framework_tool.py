"""manage_framework + the persistent toolchain tier (doc 015).

The flask lesson generalized: the container FS is lava, the volume is
land. Frameworks live at DATA_DIR/toolchain (npm prefix, pip user-base),
the tool owns the location (models never choose it), the manifest
remembers for every chat, and bash refuses global installs with
directions here.
"""
import asyncio
import json
import os

import pytest

import src.toolchain as tc
from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS
from src.agent_tools.framework_tools import ManageFrameworkTool
from src.agent_tools.subprocess_tools import _global_install_guard
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS


def test_registered_everywhere():
    assert "manage_framework" in TOOL_HANDLERS
    assert "manage_framework" in TOOL_TAGS
    names = [(s.get("function") or {}).get("name") for s in FUNCTION_TOOL_SCHEMAS]
    assert "manage_framework" in names


# ── Env: the substrate ──


def test_ensure_env_points_at_volume_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(tc, "TOOLCHAIN_DIR", tmp_path / "toolchain")
    env = tc.ensure_toolchain_env()
    assert env["NPM_CONFIG_PREFIX"] == str(tmp_path / "toolchain" / "npm")
    assert env["PYTHONUSERBASE"] == str(tmp_path / "toolchain" / "py")
    assert os.environ["NPM_CONFIG_PREFIX"] == env["NPM_CONFIG_PREFIX"]
    assert str(tmp_path / "toolchain" / "npm") in os.environ["PATH"]
    # idempotent: PATH does not grow on repeat calls
    before = os.environ["PATH"]
    tc.ensure_toolchain_env()
    assert os.environ["PATH"] == before


# ── Resolver: the decision taken away from the model ──


def test_resolver_known_and_alias():
    assert tc.resolve("vite") == {"manager": "npm", "package": "vite", "bin": "vite"}
    assert tc.resolve("tailwind")["package"] == "tailwindcss"
    assert tc.resolve("flask")["manager"] == "pip"


def test_resolver_project_deps_redirect_not_install():
    for name in ("react", "vue", "svelte", "next"):
        r = tc.resolve(name)
        assert "redirect" in r, name
        assert "PROJECT dependency" in r["redirect"]


def test_resolver_unknown_requires_manager():
    r = tc.resolve("leftpad-ultra")
    assert "error" in r and "manager" in r["error"]
    r = tc.resolve("leftpad-ultra", manager="npm")
    assert r == {"manager": "npm", "package": "leftpad-ultra"}


# ── Manifest + context line: the memory and the discovery ──


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(tc, "TOOLCHAIN_DIR", tmp_path / "toolchain")
    monkeypatch.setattr(tc, "MANIFEST_FILE", tmp_path / "toolchain" / "toolchain.json")


def test_manifest_record_and_context_line(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert tc.context_line() == ""          # empty tier → no prompt noise
    tc._record("tailwindcss", {"manager": "npm", "package": "tailwindcss", "bin": "tailwindcss"},
               "4.1", "sess1")
    tc._record("flask", {"manager": "pip", "package": "flask", "bin": "flask"}, None, "sess2")
    line = tc.context_line()
    assert "tailwindcss 4.1" in line and "flask" in line
    assert "do NOT reinstall" in line
    assert tc._unrecord("flask") is True
    assert "flask" not in tc.context_line()


def test_install_flow_records_and_verifies(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return {"rc": 0, "out": "tailwindcss 4.1.7"}

    monkeypatch.setattr(tc, "_run", fake_run)
    monkeypatch.setattr(tc.shutil, "which", lambda b: f"/toolchain/npm/bin/{b}")
    r = tc.install("tailwind", session_id="sessA")
    assert r["installed"] == "tailwindcss" and r["manager"] == "npm"
    assert calls[0][:3] == ["npm", "install", "-g"]
    assert "tailwindcss" in tc.manifest_list()          # chat B discovers it


def test_install_failure_is_honest(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(tc, "_run", lambda cmd: {"rc": 1, "out": "E404 not found"})
    r = tc.install("degit")
    assert "error" in r and "E404" in r["error"]
    assert tc.manifest_list() == {}                     # failures leave no record


def test_reconcile_reinstalls_missing(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    tc._record("vite", {"manager": "npm", "package": "vite", "bin": "vite"}, "latest", "s")
    state = {"verified": 0}

    def fake_verify(spec):
        state["verified"] += 1
        return {"ok": state["verified"] > 1}            # missing first, present after reinstall

    installs = []
    monkeypatch.setattr(tc, "_verify", fake_verify)
    monkeypatch.setattr(tc, "_run", lambda cmd: installs.append(cmd) or {"rc": 0, "out": ""})
    r = tc.reconcile()
    assert r["reinstalled"] == ["vite"] and installs


# ── Bash guard: teach-by-refusal ──


def test_guard_blocks_global_installs():
    for cmd in ("npm install -g vite", "npm i -g tailwindcss", "npm install --global sass",
                "yarn global add serve", "pnpm add -g typescript"):
        g = _global_install_guard(cmd)
        assert g is not None, cmd
        assert "manage_framework" in g["error"]


def test_guard_allows_project_local_installs():
    for cmd in ("npm install react", "npm install", "npm i tailwindcss",
                "cd myapp && npm install vue", "pip install requests", "npm run build"):
        assert _global_install_guard(cmd) is None, cmd


def test_guard_fg_override():
    assert _global_install_guard("#!fg\nnpm install -g vite") is None


# ── The tool ──


def _run_tool(payload):
    return asyncio.run(ManageFrameworkTool().execute(json.dumps(payload), {"session_id": "s1"}))


def test_tool_install_list_remove(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(tc, "_run", lambda cmd: {"rc": 0, "out": "7.1.2"})
    monkeypatch.setattr(tc.shutil, "which", lambda b: f"/bin/{b}")
    r = _run_tool({"action": "install", "name": "vite"})
    assert r["exit_code"] == 0 and "every chat can use it" in r["output"]
    r = _run_tool({"action": "list"})
    assert "vite" in r["output"]
    r = _run_tool({"action": "remove", "name": "vite"})
    assert r["exit_code"] == 0
    assert tc.manifest_list() == {}


def test_tool_redirect_and_unknown(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    r = _run_tool({"action": "install", "name": "react"})
    assert r["exit_code"] == 1 and "PROJECT dependency" in r["error"]
    r = _run_tool({"action": "install", "name": "some-unknown-thing"})
    assert r["exit_code"] == 1 and "manager" in r["error"]
