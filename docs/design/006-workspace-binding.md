# 006 — Workspace selection and confinement

**Status:** Upstream design, documented here; extension proposed (not built)

## How it works (upstream design, kept)

A workspace is a server-side folder the agent is confined to for a turn.

- **Binding is user-controlled, per request.** The UI posts `workspace` with
  each chat request; `execute_tool_block` binds it once into a contextvar
  (`tool_execution._active_workspace` — task-local, so concurrent turns
  can't leak). Three ways to set it: `/workspace pick` (server directory
  browser, `routes/workspace_routes.py`), `/workspace set /path`, or naming
  an explicit absolute path in a message
  (`chat_routes._resolve_workspace_from_message_path` binds the file's
  parent — deterministic regex, deliberately not LLM-driven).
- **Confinement:** `_resolve_tool_path` routes every file tool through
  `_resolve_tool_path_in_workspace`; paths outside the workspace are
  refused. `bash`/`python` subprocesses *start* in it (`agent_cwd()`) but
  the shell is not sandboxed. No workspace → data-dir default + allowlist.
- **Vetting** (`vet_workspace`): must exist, not a filesystem root (would
  collapse confinement into host-wide access), not a sensitive dir
  (`.ssh`, `.gnupg`, ...). Admin-only at the API layer.
- **There is deliberately no `set_workspace` tool.** Filesystem binding must
  not be model-choosable: prompt-injected content could point the agent at
  sensitive paths. The model gets `get_workspace` (read-only) only.

## Deployment caveat (copperwarehouse)

"Server filesystem" = **inside the container**. Only mounted volumes are
visible: `/app/data` ⇔ `/mnt/user/appdata/odysseus/data`. To work on a real
share, mount it (`-v /mnt/user/projects:/projects`) and bind `/projects/...`.

## Current user flow for "make a folder and work there"

The agent can `mkdir` and populate a named folder under the data dir today;
it cannot bind it. User completes the loop with `/workspace set <path>` (or
just names the path in the next message — auto-bind picks it up).

## Proposed extension (not built): scoped self-binding

A `set_workspace` tool restricted to directories **under the data dir
only** (`/app/data/projects/...`), so the agent can create and organize its
own project folders without ever being able to point itself at host paths.
Vetting reuses `vet_workspace` plus a data-dir prefix check. Decide after
the manual flow proves annoying in practice — it may not.

## Decision log

- 2026-08-04 — documented upstream design + container caveat; extension
  proposed, deliberately deferred.
