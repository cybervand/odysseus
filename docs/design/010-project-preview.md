# 010 — Project preview: display and run what the agent built

**Status:** Draft — approved direction (user, 2026-08-04), not yet built

## Problem

The agent can now build real projects (hammer-hub: React+Vite+Tailwind,
verified dist/ on disk) — but the user has no way to SEE or RUN the result
from Odysseus. A built webpage, a script, a shader: the finished artifact
dead-ends on the filesystem.

## Decision (to build)

Three tiers, smallest first:

1. **Static preview route** — `GET /preview/{path}` serving files strictly
   under the data dir (reuse `_resolve_tool_path` confinement; correct
   mime types; index.html default). A built `dist/` becomes a clickable
   link the moment it exists. Agent tools return preview URLs in results
   ("Build complete → /preview/hammer-hub/frontend/dist/"); the chat
   renders it as an open-in-new-tab card, or an iframe panel beside chat
   (the doc-panel pattern; merges the shader-preview backlog item —
   sandboxed iframe, compile errors surfaced).
2. **Script runs** — "run it" for non-web artifacts reuses bash/python +
   `manage_bg_jobs` (detached jobs already exist) with output streamed to
   the chat via the tool_progress machinery (needs the UI spinner/tail
   from the activity-indication backlog item).
3. **Dev servers** — `npm run dev` etc. as managed background jobs with a
   path-based reverse proxy (`/preview-proxy/{job}/...`) since the
   container only exposes port 80 on br1. Lifecycle owned by
   manage_bg_jobs (list/stop); policy line logs running servers
   (doc 008: no invisible state, including processes).

Security: previews only under the data dir; proxy only to job-owned
localhost ports; per the house rule every started/stopped server emits a
record.

## Decision log

- 2026-08-04 — drafted, same day the first real build (hammer-hub dist/)
  landed with nowhere to be seen.
