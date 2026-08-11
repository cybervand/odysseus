"""Background job execution for the agent's `bash` tool.

Long commands (installs, ffmpeg, model downloads) should NOT block the chat
stream — a multi-minute held SSE connection is fragile (model-stops-early,
timeouts, tab suspend). Instead we launch them **detached** and let an
always-on monitor re-invoke the agent when they finish ("auto-continue").

Design goals:
  * Restart-safe: status is derived from an on-disk exit-code file, not a live
    PID, so a uvicorn restart never loses a job or its result.
  * Idempotent follow-up: a job stays {done, followed_up: False} until the
    agent has actually been re-invoked, so completion can never silently
    "do nothing" — the monitor retries on the next tick.
  * Bounded: a hard max-runtime marks a runaway job failed and STILL triggers
    a follow-up ("timed out"), so you always hear back.

This module only owns launch + state. The monitor / agent re-invocation lives
in the caller (so this stays import-light and unit-testable).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.atomic_io import atomic_write_json
from core.platform_compat import (
    detached_popen_kwargs,
    find_bash,
    git_bash_path,
    kill_process_tree,
    pid_alive,
)

from src.constants import BG_JOBS_DIR, BG_JOBS_FILE

_JOBS_DIR = Path(BG_JOBS_DIR)
_STORE = Path(BG_JOBS_FILE)

# A job that runs longer than this is presumed stuck and reaped (the agent
# still gets a "timed out" follow-up so nothing hangs forever).
DEFAULT_MAX_RUNTIME_S = 3600  # 1 hour
# Cap how much captured output we keep / feed back to the model.
_MAX_OUTPUT_CHARS = 16000
# How long a finished-and-followed-up job (record + its .sh/.cmd.sh/.log/.exit
# files) is kept before pruning, so neither the store nor data/bg_jobs/ grows
# without bound. The agent has already consumed the result by then.
_RETENTION_S = 3600  # 1 hour after follow-up


def _load() -> Dict[str, Dict[str, Any]]:
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                return {}
            return {str(job_id): rec for job_id, rec in data.items() if isinstance(rec, dict)}
    except Exception:
        pass
    return {}


def _save(jobs: Dict[str, Dict[str, Any]]) -> None:
    atomic_write_json(str(_STORE), jobs, indent=2)


def _pid_alive(pid: Optional[int]) -> bool:
    # Delegates to the platform-safe probe. NB: a bare os.kill(pid, 0) is unsafe
    # on Windows — CPython routes it to TerminateProcess, which would KILL the
    # job we're only trying to check. core.platform_compat.pid_alive handles
    # both OSes correctly.
    return pid_alive(pid)


def launch(command: str, session_id: str, cwd: Optional[str] = None,
           max_runtime_s: int = DEFAULT_MAX_RUNTIME_S,
           env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Launch `command` detached. Returns the job record (status='running').

    Output + the final exit code are written to files so status survives a
    server restart. The process is put in its own session (setsid) so it
    outlives the request/stream that started it. `env` entries are overlaid
    on the parent environment (used for PORT assignment, doc 017).
    """
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    log_path = _JOBS_DIR / f"{job_id}.log"
    exit_path = _JOBS_DIR / f"{job_id}.exit"

    # The user command goes in its OWN script file, run as a child `bash`. This
    # is what isolates it: an `exit` inside it only ends that child (so the
    # wrapper still records the exit code), and — unlike textually wrapping the
    # command in `( … )` — the wrapper can't be broken by an unbalanced paren or
    # a trailing line-continuation in the command. `$?` is the child's real
    # exit status.
    bash = find_bash()
    if bash:
        # POSIX, or Windows with Git Bash/WSL. The user command goes in its OWN
        # script file, run as a child `bash` — an `exit` inside it only ends
        # that child (so the wrapper still records the exit code), and an
        # unbalanced paren / trailing line-continuation in the command can't
        # break the wrapper. `$?` is the child's real exit status. Paths are
        # emitted as POSIX (forward-slash) + shell-quoted so Git Bash on Windows
        # handles drive paths and spaces correctly.
        cmd_path = _JOBS_DIR / f"{job_id}.cmd.sh"
        cmd_path.write_text(command + "\n", encoding="utf-8")
        lp, xp, cp = (shlex.quote(git_bash_path(p)) for p in (log_path, exit_path, cmd_path))
        script_path = _JOBS_DIR / f"{job_id}.sh"
        script_path.write_text(
            f"bash {cp} > {lp} 2>&1\n"
            f"echo $? > {xp}\n",
            encoding="utf-8",
        )
        argv = [bash, str(script_path)]
    else:
        # Windows without any bash installed: cmd.exe wrapper. The command runs
        # in its own child .cmd so %ERRORLEVEL% is the command's real exit code.
        child_path = _JOBS_DIR / f"{job_id}.child.cmd"
        child_path.write_text("@echo off\r\n" + command + "\r\n", encoding="utf-8")
        script_path = _JOBS_DIR / f"{job_id}.cmd"
        script_path.write_text(
            "@echo off\r\n"
            f'call "{child_path}" > "{log_path}" 2>&1\r\n'
            f'echo %ERRORLEVEL%> "{exit_path}"\r\n',
            encoding="utf-8",
        )
        argv = [os.environ.get("ComSpec", "cmd.exe"), "/c", str(script_path)]

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        cwd=cwd or None,
        env={**os.environ, **env} if env else None,
        **detached_popen_kwargs(),  # detach from the request lifecycle (setsid / DETACHED_PROCESS)
    )

    rec = {
        "id": job_id,
        "session_id": session_id,
        "command": command,
        "status": "running",       # running | done | failed
        "pid": proc.pid,
        "started_at": time.time(),
        "ended_at": None,
        "exit_code": None,
        "max_runtime_s": max_runtime_s,
        "followed_up": False,       # has the agent been re-invoked with the result?
        "log_path": str(log_path),
        "exit_path": str(exit_path),
    }
    jobs = _load()
    jobs[job_id] = rec
    _save(jobs)
    return rec


def _read_output(rec: Dict[str, Any]) -> str:
    try:
        txt = Path(rec["log_path"]).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(txt) > _MAX_OUTPUT_CHARS:
        # Keep head + tail — the interesting bits are usually at both ends.
        head = txt[: _MAX_OUTPUT_CHARS // 2]
        tail = txt[-_MAX_OUTPUT_CHARS // 2:]
        txt = head + "\n…[truncated]…\n" + tail
    return txt


def _prune(jobs: Dict[str, Dict[str, Any]], now: float) -> bool:
    """Drop records (and their on-disk files) for jobs that finished, were
    followed up, and are older than the retention window. Mutates `jobs`."""
    stale = [jid for jid, rec in jobs.items()
             if rec.get("followed_up") and rec.get("ended_at")
             and (now - rec["ended_at"]) > _RETENTION_S]
    for jid in stale:
        jobs.pop(jid, None)
        for p in _JOBS_DIR.glob(f"{jid}.*"):   # .sh .cmd.sh .log .exit
            try:
                p.unlink()
            except Exception:
                pass
    return bool(stale)


def refresh() -> Dict[str, Dict[str, Any]]:
    """Reconcile every running job against disk. Marks done/failed (incl.
    timeout). Idempotent — safe to call from a poll loop. Returns the store."""
    jobs = _load()
    changed = False
    now = time.time()
    for rec in jobs.values():
        if rec.get("status") != "running":
            continue
        exit_path = Path(rec.get("exit_path", ""))
        if exit_path.exists():
            try:
                code = int(exit_path.read_text(encoding="utf-8", errors="replace").strip() or "1")
            except Exception:
                code = 1
            rec["exit_code"] = code
            rec["status"] = "done" if code == 0 else "failed"
            rec["ended_at"] = now
            changed = True
        elif (now - rec.get("started_at", now)) > rec.get("max_runtime_s", DEFAULT_MAX_RUNTIME_S):
            # Runaway / stuck — reap it but STILL surface a follow-up.
            _kill(rec.get("pid"))
            rec["status"] = "failed"
            rec["exit_code"] = -1
            rec["ended_at"] = now
            rec["timed_out"] = True
            changed = True
        elif not _pid_alive(rec.get("pid")) and not exit_path.exists():
            # Process vanished without writing an exit code (killed, OOM,
            # crash). Don't leave it "running" forever.
            rec["status"] = "failed"
            rec["exit_code"] = -1
            rec["ended_at"] = now
            rec["died"] = True
            changed = True
    if _prune(jobs, now):
        changed = True
    if changed:
        _save(jobs)
    return jobs


def _kill(pid: Optional[int]) -> None:
    # Cross-platform process-tree teardown (POSIX killpg / Windows taskkill /T).
    kill_process_tree(pid)


def pending_followups() -> List[Dict[str, Any]]:
    """Finished jobs the agent hasn't been re-invoked for yet. The monitor
    drains these; mark_followed_up() flips the flag only on success."""
    jobs = refresh()
    return [r for r in jobs.values()
            if r.get("status") in ("done", "failed") and not r.get("followed_up")]


def mark_followed_up(job_id: str) -> None:
    jobs = _load()
    if job_id in jobs:
        jobs[job_id]["followed_up"] = True
        _save(jobs)


def get(job_id: str) -> Optional[Dict[str, Any]]:
    refresh()  # reconcile against disk so status/exit_code are current
    rec = _load().get(job_id)
    if rec:
        rec = dict(rec)
        rec["output"] = _read_output(rec)
    return rec


def list_for_session(session_id: str) -> List[Dict[str, Any]]:
    return [r for r in refresh().values() if r.get("session_id") == session_id]


def kill(job_id: str) -> Optional[Dict[str, Any]]:
    """Terminate a running job's process tree and mark it killed. Returns the
    updated record, or None if the id is unknown. Idempotent: a job that already
    finished is returned unchanged. Sets followed_up so the monitor does not also
    fire an auto-continue for a job the agent deliberately stopped."""
    jobs = _load()
    rec = jobs.get(job_id)
    if rec is None:
        return None
    if rec.get("status") == "running":
        _kill(rec.get("pid"))
        rec["status"] = "failed"
        rec["exit_code"] = -1
        rec["ended_at"] = time.time()
        rec["killed"] = True
        rec["followed_up"] = True
        _save(jobs)
    return rec


# ── Named servers (doc 014 follow-on, the stale-process lesson) ──
# A server is a long-lived named job: no 1h reaping, restartable by name.
# "Edit the code" and "change the behavior" are different things until the
# process restarts — `restart` is the verb that reconciles them.

_SERVERS_FILE = _JOBS_DIR / "servers.json"
SERVER_MAX_RUNTIME_S = 7 * 24 * 3600

# ── Port range + ownership (doc 017) ──
# Servers get ports ASSIGNED from a reserved range instead of self-reporting
# them (skilodge drift: registry said 8091, app.py bound 8090 — nothing
# checked). The launched process receives PORT in its environment; the range
# stays clear of cookbook's model-serving allocator (8000+) and every common
# dev default. NO per-user caps — homelab; the range is the backstop.
_DEFAULT_PORT_RANGE = (13000, 13999)

# Boot/deploy relaunches are owned by the system, not a chat. bg_monitor
# skips follow-ups for this owner (and the legacy "__ops__" fake session
# that made it retry-spam "Session __ops__ not found" forever).
SYSTEM_OWNER = "__system__"
LEGACY_OPS_SESSION = "__ops__"


class PortAllocationError(ValueError):
    """Raised with a TEACHING message: every port failure names the cause and
    the next action — never a bare 'address in use' (doc 017 §1)."""


def port_range() -> tuple:
    raw = os.environ.get("ODYSSEUS_SERVER_PORT_RANGE", "")
    m = re.match(r"^\s*(\d{2,5})\s*-\s*(\d{2,5})\s*$", raw)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 <= lo <= hi <= 65535:
            return lo, hi
    return _DEFAULT_PORT_RANGE


def _allocate_port(servers: Dict[str, Dict[str, Any]], name: str,
                   requested: Optional[int]) -> int:
    """Assign a port for server `name`. Diagnoses conflicts by owner instead
    of reporting them. Grandfathering: a server keeps its previously stored
    port even if out of range (skilodge 8090, qwenmax-lodge 3000)."""
    lo, hi = port_range()
    existing = servers.get(name) or {}
    if requested is not None and requested == existing.get("port"):
        return requested  # same server, same port — stability across restarts
    taken = {e.get("port"): n for n, e in servers.items()
             if n != name and e.get("port")}
    if requested is not None:
        if not (lo <= requested <= hi):
            raise PortAllocationError(
                f"port {requested} is outside Odysseus's server port range "
                f"{lo}-{hi}. Omit 'port' and one is assigned to you "
                f"automatically — your app reads it from the PORT env var.")
        if requested in taken:
            other = servers.get(taken[requested]) or {}
            other_job = _load().get(other.get("job_id", "")) or {}
            state = "still running" if other_job.get("status") == "running" else "stopped"
            raise PortAllocationError(
                f"port {requested} belongs to your server '{taken[requested]}' "
                f"({state}). Restart that server to apply code edits, stop it, "
                f"or omit 'port' for a fresh assignment.")
        if _port_listening(requested):
            raise PortAllocationError(
                f"port {requested} is busy (something outside the registry is "
                f"listening). Omit 'port' and you are assigned a free one — "
                f"your app reads it from the PORT env var.")
        return requested
    for p in range(lo, hi + 1):
        if p in taken:
            continue
        if existing.get("port") == p or not _port_listening(p):
            return p
    raise PortAllocationError(
        f"all ports in {lo}-{hi} are in use. Stop or remove servers you no "
        f"longer need (action 'list' shows them, 'remove' deletes one).")


def _load_servers() -> Dict[str, Dict[str, Any]]:
    try:
        if _SERVERS_FILE.exists():
            data = json.loads(_SERVERS_FILE.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_servers(servers: Dict[str, Dict[str, Any]]) -> None:
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(_SERVERS_FILE), servers, indent=2)


_DEV_HOST_FLAGS = {
    "vite": " -- --host 0.0.0.0",
    "next": " -- -H 0.0.0.0",
}


def _lan_host_fix(command: str, cwd: Optional[str]):
    """Make a known dev-server command listen on the LAN.

    Vite and Next bind the loopback address by default. Such a server
    answers inside the container only. The user's browser gets a
    refused connection (seen 2026-08-12, hawaii-history-react).
    Returns (command, note). The note is None when nothing changed.
    """
    lowered = command.lower()
    if "0.0.0.0" in lowered or "--host" in lowered:
        return command, None
    if not ("npm run dev" in lowered or "npx vite" in lowered
            or "vite dev" in lowered or "next dev" in lowered):
        return command, None
    framework = None
    try:
        with open(os.path.join(cwd or ".", "package.json"), encoding="utf-8") as f:
            pkg = json.load(f)
        deps = {}
        deps.update(pkg.get("dependencies") or {})
        deps.update(pkg.get("devDependencies") or {})
        if "vite" in deps:
            framework = "vite"
        elif "next" in deps:
            framework = "next"
    except (OSError, ValueError):
        pass
    if framework is None and "vite" in lowered:
        framework = "vite"
    if framework is None:
        return command, ("note: dev servers often listen on the loopback "
                         "address only — make sure this one listens on 0.0.0.0")
    fixed = command + _DEV_HOST_FLAGS[framework]
    return fixed, (f"note: added a LAN host flag for {framework} — its dev "
                   "server listens on the loopback address by default, and "
                   "the LAN gets no answer")


def server_start(name: str, command: str, session_id: str,
                 cwd: Optional[str] = None, port: Optional[int] = None,
                 owner: Optional[str] = None,
                 autostart: Optional[bool] = None) -> Dict[str, Any]:
    """Start (or replace) the named server, detached and unreaped.

    The port is ASSIGNED (doc 017): allocated from the reserved range unless
    the caller names a valid free one, injected into the process as PORT.
    Owner/autostart are sticky — a replace without them keeps the old values.
    Raises PortAllocationError with a teaching message on any port problem.
    """
    # Correct known dev-server commands so the LAN can reach them. The
    # registry stores the corrected command, and restarts keep it.
    command, _host_note = _lan_host_fix(command, cwd)
    servers = _load_servers()
    old = servers.get(name)
    assigned = _allocate_port(servers, name, port if port else (old or {}).get("port"))
    if old and old.get("job_id"):
        kill(old["job_id"])   # replacing an existing instance is deliberate
    rec = launch(command, session_id, cwd=cwd, max_runtime_s=SERVER_MAX_RUNTIME_S,
                 env={"PORT": str(assigned)})
    servers[name] = {"job_id": rec["id"], "command": command, "cwd": cwd,
                     "port": assigned, "session_id": session_id,
                     "owner": owner if owner is not None else (old or {}).get("owner"),
                     "autostart": autostart if autostart is not None
                     else bool((old or {}).get("autostart")),
                     "started_at": rec["started_at"]}
    _save_servers(servers)
    status = server_status(name)
    if _host_note and isinstance(status, dict):
        status["note"] = _host_note
    return status


def server_stop(name: str) -> Optional[Dict[str, Any]]:
    servers = _load_servers()
    entry = servers.get(name)
    if not entry:
        return None
    kill(entry.get("job_id", ""))
    entry["stopped"] = True
    _save_servers(servers)
    return server_status(name)


def server_restart(name: str) -> Optional[Dict[str, Any]]:
    """Stop + start with the SAME command/cwd/port — applies code edits."""
    entry = _load_servers().get(name)
    if not entry:
        return None
    return server_start(name, entry["command"], entry.get("session_id", ""),
                        cwd=entry.get("cwd"), port=entry.get("port"),
                        owner=entry.get("owner"),
                        autostart=entry.get("autostart"))


def server_assign(name: str, session_id: str) -> Optional[Dict[str, Any]]:
    """Re-attach a server to another chat (doc 017: capability follows the
    owner, attachment follows the session — and moving it is always explicit,
    never a side effect of touching it from elsewhere)."""
    servers = _load_servers()
    entry = servers.get(name)
    if not entry:
        return None
    entry["session_id"] = session_id
    _save_servers(servers)
    return server_status(name)


def server_remove(name: str) -> Optional[Dict[str, Any]]:
    """Delete the registry entry (killing the process first if running).
    `stop` deliberately keeps the entry restartable; this is the actual
    delete the registry never had — dead entries otherwise live forever."""
    servers = _load_servers()
    entry = servers.pop(name, None)
    if entry is None:
        return None
    if entry.get("job_id"):
        kill(entry["job_id"])
    _save_servers(servers)
    entry["removed"] = True
    return entry


def reconcile_autostart() -> List[str]:
    """Boot-time self-heal (doc-015 pattern): relaunch every autostart-flagged
    server that is not running. Called from app startup — retires the deploy
    script's hand-written skilodge relaunch. The relaunched JOB is owned by
    SYSTEM_OWNER (no chat follow-up on its eventual exit); the entry keeps its
    chat attachment for panel attribution."""
    revived = []
    for name, entry in _load_servers().items():
        if not entry.get("autostart") or entry.get("stopped"):
            continue
        job = get(entry.get("job_id", "")) or {}
        if job.get("status") == "running":
            continue
        try:
            saved_session = entry.get("session_id", "")
            server_start(name, entry["command"], SYSTEM_OWNER,
                         cwd=entry.get("cwd"), port=entry.get("port"),
                         owner=entry.get("owner"),
                         autostart=True)
            # server_start stamped the entry with the SYSTEM job session;
            # restore the chat attachment (it belongs to the panel, not the job).
            if saved_session and saved_session != SYSTEM_OWNER:
                server_assign(name, saved_session)
            revived.append(name)
        except Exception:
            # One broken server must not block the rest of boot reconciliation.
            continue
    return revived


def _port_listening(port: Optional[int]) -> Optional[bool]:
    if not port:
        return None
    import socket
    try:
        s = socket.socket()
        s.settimeout(2)
        ok = s.connect_ex(("127.0.0.1", int(port))) == 0
        s.close()
        return ok
    except Exception:
        return None


def server_status(name: str) -> Optional[Dict[str, Any]]:
    entry = _load_servers().get(name)
    if not entry:
        return None
    job = get(entry.get("job_id", "")) or {}
    return {
        "name": name,
        "command": entry.get("command"),
        "cwd": entry.get("cwd"),
        "port": entry.get("port"),
        "running": job.get("status") == "running",
        "port_listening": _port_listening(entry.get("port")),
        "uptime_s": round(time.time() - entry.get("started_at", time.time()), 1)
        if job.get("status") == "running" else None,
        "job_id": entry.get("job_id"),
        "exit_code": job.get("exit_code"),
        "owner": entry.get("owner"),
        "session_id": entry.get("session_id"),
        "autostart": bool(entry.get("autostart")),
        "stopped": bool(entry.get("stopped")),
    }


def server_list() -> List[Dict[str, Any]]:
    return [server_status(n) for n in _load_servers().keys()]


def server_logs(name: str, tail_chars: int = 4000) -> Optional[str]:
    entry = _load_servers().get(name)
    if not entry:
        return None
    job = get(entry.get("job_id", "")) or {}
    out = job.get("output") or ""
    return out[-tail_chars:] if out else "(no output yet)"


def result_text(rec: Dict[str, Any]) -> str:
    """Human/agent-readable summary of a finished job, for the follow-up."""
    out = _read_output(rec)
    if rec.get("killed"):
        head = "Background job was killed."
    elif rec.get("timed_out"):
        head = f"Background job timed out after {rec.get('max_runtime_s')}s."
    elif rec.get("died"):
        head = "Background job process died unexpectedly (no exit code)."
    else:
        head = f"Background job finished with exit code {rec.get('exit_code')}."
    return f"{head}\nCommand: {rec.get('command')}\n\nOutput:\n{out or '(no output)'}"
