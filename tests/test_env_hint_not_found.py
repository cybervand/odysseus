"""Env hint on missing binaries (doc 013 world-model-update failure).

Observed on gpt-oss and qwen the same day: `lsof: not found` triggers the
trained troubleshooting liturgy (netstat, ss, fuser — all equally missing)
instead of the inference "this container is minimal." The bash tool now
appends one env hint at the first not-found, naming what exists.
"""
from src.agent_tools.subprocess_tools import _NOT_FOUND_RE, _maybe_env_hint


def test_not_found_re_matches_observed_shapes():
    for line in (
        "/bin/sh: 1: lsof: not found",
        "sh: 1: netstat: not found",
        "bash: fuser: command not found",
    ):
        m = _NOT_FOUND_RE.search(line)
        assert m, line
        assert m.group(1) in ("lsof", "netstat", "fuser")


def test_not_found_re_ignores_other_stderr():
    assert _NOT_FOUND_RE.search("curl: (7) Failed to connect") is None
    assert _NOT_FOUND_RE.search("FileNotFoundError: [Errno 2] No such file") is None


def test_hint_appended_for_missing_binary():
    hint = _maybe_env_hint("/bin/sh: 1: lsof: not found")
    assert "[env hint]" in hint
    assert "'lsof'" in hint
    assert "python3" in hint           # names a real alternative


def test_no_hint_on_normal_failure():
    assert _maybe_env_hint("") == ""
    assert _maybe_env_hint("curl: (7) Failed to connect") == ""
