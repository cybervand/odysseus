import asyncio
import os
import re
import shutil
import sys
import time
import collections
from typing import Optional, Callable, Awaitable, Tuple, Dict
from src.constants import MAX_OUTPUT_CHARS

DEFAULT_BASH_TIMEOUT = 60 * 60     # 1 hour
DEFAULT_PYTHON_TIMEOUT = 60 * 60

PROGRESS_INTERVAL_S = 2.0
PROGRESS_TAIL_LINES = 12
TMUX_CAPTURE_LINES = 2000


# ANSI/VT escape sequences (colors, cursor moves, show/hide cursor) that CLIs
# emit when they mistake the pipe for a terminal. They reach the model's
# context and the chat UI as literal garbage ("[1m[36m[?25l..."), wasting
# tokens and obscuring the real output — strip them from captured output.
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"   # CSI sequences (colors, cursor control)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences (titles, links)
    r"|\x1b[@-Z\\-_]"              # two-byte escapes
)


def _strip_ansi(text: str) -> str:
    if not text or "\x1b" not in text:
        return text
    return _ANSI_ESCAPE_RE.sub("", text)


def _tmux_session_name(session_id: Optional[str]) -> str:
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(session_id or "default")).strip("-")
    return f"ody-agent-{raw[:80] or 'default'}"


async def _run_exec(*args: str, timeout: float = 10) -> Tuple[str, str, int]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return "", "timeout", 124
    return (
        out_b.decode("utf-8", errors="replace"),
        err_b.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


async def _tmux_has_session(name: str) -> bool:
    _, _, rc = await _run_exec("tmux", "has-session", "-t", name, timeout=3)
    return rc == 0


async def _tmux_capture(name: str) -> str:
    out, _, _ = await _run_exec(
        "tmux", "capture-pane", "-p", "-J", "-S", f"-{TMUX_CAPTURE_LINES}", "-t", name,
        timeout=5,
    )
    return out


async def _tmux_send_line(name: str, line: str) -> None:
    if line:
        await _run_exec("tmux", "send-keys", "-t", name, "-l", line, timeout=5)
    await _run_exec("tmux", "send-keys", "-t", name, "C-m", timeout=5)


async def _ensure_tmux_session(name: str, cwd: str, env: Optional[dict]) -> None:
    if await _tmux_has_session(name):
        await _run_exec("tmux", "send-keys", "-t", name, "stty -echo", "C-m", timeout=5)
        return
    await _run_exec(
        "tmux", "new-session", "-d", "-s", name, "-c", cwd,
        "env",
        f"TERM={env.get('TERM', 'xterm-256color') if env else 'xterm-256color'}",
        f"COLUMNS={env.get('COLUMNS', '120') if env else '120'}",
        f"LINES={env.get('LINES', '40') if env else '40'}",
        "/bin/bash",
        "--noprofile",
        "--norc",
        timeout=10,
    )
    if not await _tmux_has_session(name):
        raise RuntimeError(f"failed to create tmux session {name}")
    await _run_exec("tmux", "send-keys", "-t", name, "stty -echo", "C-m", timeout=5)


def _output_after_marker(capture: str, start_marker: str, end_marker: str) -> Tuple[str, bool]:
    lines = capture.splitlines()
    start_idx = -1
    for idx, line in enumerate(lines):
        if line.strip() == start_marker:
            start_idx = idx
    if start_idx < 0:
        return capture, False
    end_idx = -1
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].strip().startswith(end_marker):
            end_idx = idx
    if end_idx < 0:
        return "\n".join(lines[start_idx + 1:]), False
    return "\n".join(lines[start_idx + 1:end_idx]), True


def _extract_marker_rc(capture: str, end_marker: str) -> int:
    for line in reversed(capture.splitlines()):
        stripped = line.strip()
        if stripped.startswith(end_marker):
            suffix = stripped[len(end_marker):].strip()
            if suffix.isdigit():
                return int(suffix)
    return 0


async def _run_tmux_bash(
    content: str,
    *,
    session_id: str,
    cwd: str,
    env: Optional[dict],
    timeout: float,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
) -> Tuple[str, str, Optional[int], bool]:
    name = _tmux_session_name(session_id)
    await _ensure_tmux_session(name, cwd, env)

    stamp = f"{int(time.time() * 1000)}-{abs(hash(content)) % 1000000}"
    start_marker = f"__ODYSSEUS_CMD_START_{stamp}__"
    end_prefix = f"__ODYSSEUS_CMD_END_{stamp}__:"
    wrapped = (
        f"printf '\\n{start_marker}\\n'\n"
        f"{content}\n"
        f"__ody_rc=$?\n"
        f"printf '\\n{end_prefix}%s\\n' \"$__ody_rc\"\n"
    )
    for line in wrapped.splitlines():
        await _tmux_send_line(name, line)

    started = time.time()
    last_tail = ""
    while True:
        capture = await _tmux_capture(name)
        body, done = _output_after_marker(capture, start_marker, end_prefix)
        tail = "\n".join(body.splitlines()[-PROGRESS_TAIL_LINES:])
        if progress_cb and tail != last_tail:
            last_tail = tail
            try:
                await progress_cb({
                    "elapsed_s": round(time.time() - started, 1),
                    "tail": tail,
                    "tmux_session": name,
                })
            except Exception:
                pass
        if done:
            rc = _extract_marker_rc(capture, end_prefix)
            cleaned = _clean_tmux_command_output(body, wrapped)
            return cleaned, "", rc, False
        if time.time() - started > timeout:
            try:
                await _run_exec("tmux", "send-keys", "-t", name, "C-c", timeout=3)
            except Exception:
                pass
            cleaned = _clean_tmux_command_output(body, wrapped)
            return cleaned, "", 124, True
        await asyncio.sleep(0.5)


def _clean_tmux_command_output(text: str, wrapped_command: str) -> str:
    lines = text.splitlines()
    wrapped_lines = {ln.rstrip() for ln in wrapped_command.splitlines() if ln.strip()}
    cleaned = []
    for line in lines:
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped:
            cleaned.append(raw)
            continue
        if stripped in wrapped_lines:
            continue
        if stripped.startswith("__ody_rc=") or stripped.startswith("printf "):
            continue
        if re.fullmatch(r"(?:bash|sh)-[\d.]+\$ ?", stripped):
            continue
        if re.fullmatch(r"[\w.@:/~+-]+[#$] ?", stripped):
            continue
        cleaned.append(raw)
    return "\n".join(cleaned).strip()

async def _run_subprocess_streaming(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
) -> Tuple[str, str, Optional[int], bool]:
    started = time.time()
    stdout_full: list[str] = []
    stderr_full: list[str] = []
    tail = collections.deque(maxlen=PROGRESS_TAIL_LINES)

    async def _reader(stream, full_buf, label: str):
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\n")
            full_buf.append(decoded)
            if label == "err":
                tail.append(f"! {decoded}")
            else:
                tail.append(decoded)

    async def _progress_emitter():
        await asyncio.sleep(PROGRESS_INTERVAL_S)
        while True:
            if progress_cb:
                try:
                    await progress_cb({
                        "elapsed_s": round(time.time() - started, 1),
                        "tail": "\n".join(list(tail)),
                    })
                except Exception:
                    pass
            await asyncio.sleep(PROGRESS_INTERVAL_S)

    rd_out = asyncio.create_task(_reader(proc.stdout, stdout_full, "out"))
    rd_err = asyncio.create_task(_reader(proc.stderr, stderr_full, "err"))
    prog_task = asyncio.create_task(_progress_emitter()) if progress_cb else None

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
    except asyncio.CancelledError:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
        for t in (rd_out, rd_err):
            t.cancel()
        if prog_task is not None:
            prog_task.cancel()
        raise
    finally:
        if prog_task is not None and not prog_task.done():
            prog_task.cancel()
            try:
                await prog_task
            except (asyncio.CancelledError, Exception):
                pass
        for t in (rd_out, rd_err):
            try:
                await asyncio.wait_for(t, timeout=1)
            except Exception:
                pass

    return (
        "\n".join(stdout_full),
        "\n".join(stderr_full),
        proc.returncode,
        timed_out,
    )

# Commands that never return: running them in foreground bash holds the
# tool call (and the whole run) hostage until timeout — it happened three
# times in one day (npm run dev, vite preview, python app.py/flask).
# Foreground bash REFUSES them with directions to manage_server; a first
# line of `#!fg` overrides for genuinely finite scripts.
_SERVER_CMD_RE = re.compile(
    r"\b(npm run dev|npm start|yarn dev|pnpm dev|vite preview|vite dev|"
    r"flask run|python[0-9.]* -m http\.server|uvicorn |gunicorn |"
    # Path-qualified launches must match too: `python /app/data/app.py`
    # dodged the bare `python app.py` pattern (2026-08-07 lodge_website
    # run) and held the run hostage to the 300s timeout — the user saw a
    # 502 and queued messages.
    r"ng serve|next dev|python[0-9.]* (?:\S*/)?(?:app|server|wsgi)\.py|"
    r"node (?:\S*/)?(?:server|app|index)\.js)\b"
)

# Shape-independent second net: SERVER CODE inside inline payloads. Dodge
# #3 (2026-08-07): `python3 -c "import http.server; …serve_forever()"` —
# no filename, no known launcher, still a never-returning server. Match
# what server code IS, not how it's spelled on the command line.
_SERVER_CODE_RE = re.compile(
    r"serve_forever\s*\(|socketserver\.|http\.server|HTTPServer\s*\(|"
    r"run_simple\s*\(|createServer\s*\(|app\.run\s*\("
)


def _server_command_guard(content: str):
    """Return an error dict when the command is a known never-returning
    server launch (and not #!fg-overridden); else None."""
    lines = content.split("\n")
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    if first.lower() in ("#!fg", "# fg"):
        return None
    m = _SERVER_CMD_RE.search(content) or _SERVER_CODE_RE.search(content)
    if not m:
        return None
    return {
        "error": (
            f"bash: refusing to run '{m.group(1) if m.lastindex else m.group(0)}' in the foreground — it never "
            "exits, so it would hold this tool call hostage until timeout. "
            "Use your manage_server tool instead: "
            '{"action": "start", "name": "myapp", "command": "<the command>", '
            '"cwd": "<project dir>"} — the port is ASSIGNED automatically and '
            "exported to your app as the PORT env var (do not pick one). Then "
            'manage_server {"action": "restart", "name": "myapp"} after EVERY '
            "code edit (edits do not apply to a running process), and "
            '{"action": "logs", "name": "myapp"} to read its output. '
            "If this really is a finite script, resend with #!fg as the first line."
        ),
        "exit_code": 1,
    }


# Global installs in bash land in whatever tier the package manager
# defaults to — historically the ephemeral container FS, where they die on
# deploy (the flask lesson, doc 015). manage_framework owns the persistent
# tier; bash redirects there. Project-LOCAL installs (plain `npm install`
# in a project dir) stay allowed — that is the correct default.
_GLOBAL_INSTALL_RE = re.compile(
    r"\b(npm (?:install|i|add) (?:-g|--global)|npm (?:-g|--global) (?:install|i|add)|"
    r"yarn global add|pnpm (?:add|install) (?:-g|--global))\b"
)


def _global_install_guard(content: str):
    """Return an error dict when the command is a global package install
    (and not #!fg-overridden); else None."""
    lines = content.split("\n")
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    if first.lower() in ("#!fg", "# fg"):
        return None
    m = _GLOBAL_INSTALL_RE.search(content)
    if not m:
        return None
    return {
        "error": (
            f"bash: refusing '{m.group(1)}' — global installs from bash land in "
            "the wrong tier and vanish on the next app update. Use your "
            'manage_framework tool instead: {"action": "install", "name": '
            '"<framework>"} — it installs to the persistent shared tier, every '
            "chat can use it, and it survives updates. Project-local deps are "
            "different: plain `npm install <pkg>` inside your project folder is "
            "correct and allowed."
        ),
        "exit_code": 1,
    }


# `sh: 1: lsof: not found` / `bash: netstat: command not found`
_NOT_FOUND_RE = re.compile(r"(?:^|\n)(?:/bin/)?(?:ba)?sh: (?:\d+: )?([\w.+-]+): (?:command )?not found", re.MULTILINE)


def _maybe_env_hint(err: str) -> str:
    """One-shot world-model teaching for 'X: not found' stderr (doc 013):
    without it models walk the trained troubleshooting liturgy (lsof →
    netstat → ss → fuser, each equally absent) instead of concluding the
    container is minimal. Returns "" when no hint applies."""
    m = _NOT_FOUND_RE.search(err) if err else None
    if not m:
        return ""
    return (
        f"\n[env hint] '{m.group(1)}' does not exist in this minimal "
        "container — neither do lsof, netstat, ss, fuser, vim, nano or "
        "jq. Do not try other missing binaries; use what exists: "
        "python3, curl, ps, grep, sed, awk, find, git, npm/node. "
        "To check a port: python3 -c \"import socket; "
        "print(socket.socket().connect_ex(('127.0.0.1', PORT)))\" "
        "(0 = something is listening)."
    )


class BashTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import agent_cwd, _truncate
        if isinstance(content, dict):
            content = str(content.get("command") or content.get("cmd") or content.get("code") or "")
        _guard = _server_command_guard(content or "") or _global_install_guard(content or "")
        if _guard:
            return _guard
        progress_cb = ctx.get("progress_cb")
        _subproc_env = ctx.get("subproc_env")
        session_id = ctx.get("session_id")
        if session_id and shutil.which("tmux"):
            stdout, stderr, rc, timed_out = await _run_tmux_bash(
                content,
                session_id=str(session_id),
                cwd=agent_cwd(),
                env=_subproc_env,
                timeout=DEFAULT_BASH_TIMEOUT,
                progress_cb=progress_cb,
            )
            if timed_out:
                return {
                    "error": f"bash: timed out after {DEFAULT_BASH_TIMEOUT}s — sent Ctrl-C to tmux session",
                    "exit_code": 124,
                    "stdout": _truncate(stdout, MAX_OUTPUT_CHARS),
                    "stderr": _truncate(stderr, MAX_OUTPUT_CHARS),
                    "tmux_session": _tmux_session_name(str(session_id)),
                }
            output = _strip_ansi(stdout).rstrip()
            err = _strip_ansi(stderr).rstrip()
            if err:
                output = (output + "\nSTDERR: " + err).strip() if output else "STDERR: " + err
            return {
                "output": _truncate(output, MAX_OUTPUT_CHARS) or "(no output)",
                "exit_code": rc or 0,
                "tmux_session": _tmux_session_name(str(session_id)),
            }

        proc = await asyncio.create_subprocess_shell(
            content,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subproc_env,
            cwd=agent_cwd(),
        )
        stdout, stderr, rc, timed_out = await _run_subprocess_streaming(
            proc,
            timeout=DEFAULT_BASH_TIMEOUT,
            progress_cb=progress_cb,
        )
        if timed_out:
            return {"error": f"bash: timed out after {DEFAULT_BASH_TIMEOUT}s — process killed", "exit_code": 124, "stdout": _truncate(stdout, MAX_OUTPUT_CHARS), "stderr": _truncate(stderr, MAX_OUTPUT_CHARS)}
        output = _strip_ansi(stdout).rstrip()
        err = _strip_ansi(stderr).rstrip()
        if err:
            output = (output + "\nSTDERR: " + err).strip() if output else "STDERR: " + err
        output = _truncate(output, MAX_OUTPUT_CHARS)
        output += _maybe_env_hint(err)
        return {"output": output or "(no output)", "exit_code": rc or 0}

class PythonTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.tool_execution import agent_cwd, _truncate
        progress_cb = ctx.get("progress_cb")
        _subproc_env = ctx.get("subproc_env")
        proc = await asyncio.create_subprocess_exec(
            # No -I: isolated mode hides pip's user-site installs, so agent
            # code could `pip install` via bash yet never import the result.
            (sys.executable or "python"), "-c", content,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subproc_env,
            cwd=agent_cwd(),
        )
        stdout, stderr, rc, timed_out = await _run_subprocess_streaming(
            proc,
            timeout=DEFAULT_PYTHON_TIMEOUT,
            progress_cb=progress_cb,
        )
        if timed_out:
            return {"error": f"python: timed out after {DEFAULT_PYTHON_TIMEOUT}s — process killed", "exit_code": 124, "stdout": _truncate(stdout, MAX_OUTPUT_CHARS), "stderr": _truncate(stderr, MAX_OUTPUT_CHARS)}
        output = _strip_ansi(stdout).rstrip()
        err = _strip_ansi(stderr).rstrip()
        if err:
            output = (output + "\nSTDERR: " + err).strip() if output else "STDERR: " + err
        output = _truncate(output, MAX_OUTPUT_CHARS)
        return {"output": output or "(no output)", "exit_code": rc or 0}
