"""Contract tests for the verifier toggle chain (command menu → settings).

Two real bugs shipped 2026-08-11 that these lock down:
1. `agent_verifier_subagent` was absent from DEFAULT_SETTINGS, so the
   POST settings route's whitelist silently dropped every UI write.
2. The command-menu fetches targeted `/api/settings`, which is not a
   mounted route (the auth router lives at `/api/auth`) — every request
   404'd, the GET was silently swallowed, and the switch could never
   turn on. Evidence: settings.json mtime five days older than the
   toggle attempts, and a log full of 404s.
"""

from pathlib import Path


def test_default_settings_registers_verifier_key():
    """Required so /api/auth/settings and manage_settings can persist it."""
    from src.settings import DEFAULT_SETTINGS
    assert "agent_verifier_subagent" in DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["agent_verifier_subagent"] is False


def test_agent_loop_reads_the_registered_key():
    """The gate must read the same key the settings route persists."""
    src = Path("src/agent_loop.py").read_text(encoding="utf-8")
    assert 'get_setting("agent_verifier_subagent"' in src


def test_settings_roundtrip_accepts_verifier_key():
    """The save path must persist the key (whitelist inclusion, not drop)."""
    from src.settings import DEFAULT_SETTINGS
    # The POST route iterates DEFAULT_SETTINGS as its whitelist; membership
    # plus a plain-bool default is what makes the write survive it.
    assert isinstance(DEFAULT_SETTINGS["agent_verifier_subagent"], bool)


def test_frontend_calls_the_mounted_settings_route():
    """The auth router mounts at /api/auth — a fetch to /api/settings 404s.

    This is the exact bug: the command-menu wiring called the unmounted
    path and the switch was dead with no visible error.
    """
    # The command menu moved to a fork module (doc 021, phase 2).
    fork_js = Path("static/js/fork/commandMenu.js").read_text(encoding="utf-8")
    assert "'/api/auth/settings'" in fork_js, (
        "command menu must call the mounted settings route"
    )
    for f in ("static/js/fork/commandMenu.js", "static/app.js"):
        src = Path(f).read_text(encoding="utf-8")
        assert "fetch('/api/settings'" not in src, (
            f"{f}: /api/settings is not a mounted route (auth router "
            "prefix is /api/auth) — a fetch to it 404s and the control dies"
        )
