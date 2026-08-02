"""write_file must recover when an empty file squats on a directory path.

Observed three times across live gpt-oss runs: the model calls
`write_file /app/data/haikus` (the directory path, empty body), creating a
zero-byte FILE. Every subsequent `write_file /app/data/haikus/haiku-*.txt`
then dies in makedirs with FileExistsError, the model misreads the cryptic
error as missing permissions ("/app is outside the permitted roots") and
abandons the task. A zero-byte squatter carries no data — replace it. A
file WITH content must never be deleted; the error must say what's wrong.
"""
import asyncio

import pytest

import src.tool_execution as tool_execution
from src.agent_tools.filesystem_tools import WriteFileTool


@pytest.fixture(autouse=True)
def _roots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tool_execution, "_resolve_tool_path", lambda p: str(tmp_path / p.lstrip("/\\"))
    )
    return tmp_path


def _write(arg: str) -> dict:
    return asyncio.run(WriteFileTool().execute(arg, {}))


def test_empty_squatter_file_is_replaced_by_directory(_roots):
    _write("data/haikus\n")  # the fumble: empty file at the dir path
    assert (_roots / "data" / "haikus").is_file()

    res = _write("data/haikus/haiku-servers.txt\nquiet hum of racks")
    assert res.get("exit_code") == 0, res
    assert (_roots / "data" / "haikus").is_dir()
    assert (_roots / "data" / "haikus" / "haiku-servers.txt").read_text() == "quiet hum of racks"


def test_nonempty_file_is_never_deleted(_roots):
    (_roots / "data").mkdir()
    (_roots / "data" / "haikus").write_text("precious")

    res = _write("data/haikus/haiku-servers.txt\nquiet hum of racks")
    assert res.get("exit_code") == 1
    assert "exists as a FILE" in res.get("error", "")
    assert (_roots / "data" / "haikus").read_text() == "precious"


def test_normal_nested_write_still_works(_roots):
    res = _write("a/b/c/deep.txt\nhello")
    assert res.get("exit_code") == 0, res
    assert (_roots / "a" / "b" / "c" / "deep.txt").read_text() == "hello"
