# 005 — Document diff pipeline

**Status:** Shipped (0cf537a9, 9a41a74f, 3b374ef3)

## Problem

Three consumers needed to know *what changed* when the AI touches a
document, and none did: the user wanted VS-Code-style visibility (green
added / red deleted, a `+N −M` count); the editor's review mode only
triggered on ≥3 changed lines and only when the doc was the focused tab; and
the completion verifier judged edits blind (doc 002 §5).

## Decision

One diff, computed once, consumed three times. `document_tools._doc_diff`
(reuses `filesystem_tools._unified_diff`) attaches
`{text, added, removed, new_file, file}` to every create/update/edit result.

- **Chat:** `agent_loop` copies `result.diff` onto the `tool_output` SSE
  event; the live renderer (chat.js ~3153) and the reload renderer
  (chatRenderer ~2400, via the persisted `tool_event.diff`) already rendered
  that shape for file edits — document edits got the `+N −M` chip and
  colored diff for free.
- **Editor:** the existing AI-edit diff-review mode (interleaved old/new
  lines, per-chunk accept/reject) now triggers on every edit
  (`DIFF_MODE_THRESHOLD` 3→1) and captures old content from the doc map as
  fallback, not just the live textarea — edits landing while the panel is
  docked or another tab is focused still highlight.
- **Verifier:** `_build_actions_snapshot` appends each event's diff head.

Styling: editor diff lines use the git convention — `--green`/`--red`
22% background tints, border-left bars, normal text color (the previous
blue-added / yellow-strikethrough-deleted read as anything but a diff).
Matches the chat card's `.diff-pre` styling exactly.

## Rejected alternatives

- **Separate diff implementations per consumer** — one shape, one truth;
  divergence here means the verifier judges a different diff than the user
  sees.
- **Highlight-only overlay for the editor** (no review mode) — the
  accept/reject machinery already existed and is the better UX for AI edits.

## Hard-won operational rule

**Bump the `?v=` cache-buster in static/index.html for EVERY frontend
change.** document.js's was stale from July 22 — a night of deploys never
reached the browser. There is no build pipeline doing this automatically.

## Validation

`tests/test_document_diff_stats.py`; deterministic lab edit returned
`+1 −1` with correct unified diff; live qwen edit produced the full
green/red review flow.

## Open items

- Creates show a flash + `new +N` chip rather than highlighting (an all-new
  doc would be solid green); revisit if users want it.
- Automate cache-buster bumping (hash-based versioning) — manual rule for now.

## Decision log

- 2026-08-04 — diff emission + threshold + verifier snapshot (0cf537a9);
  old-content fallback + cache bump (9a41a74f); green/red styling (3b374ef3).
