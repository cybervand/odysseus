# 021 — QoL: slimming the giants without severing the upstream lifeline

**Status:** Draft (2026-08-11). Strategy settled; phase 1 ready to build.

## Problem

Measured today (lines):

| File | Lines | Owner of churn |
|---|---|---|
| `static/style.css` | 41,249 | both |
| `src/agent_loop.py` | 6,207 | upstream (#3266 pending) + fork (dialect/verifier territory) |
| `static/js/chat.js` | 6,165 | upstream (stream machinery) + fork (reconcile, queue) |
| `routes/email_routes.py` | 6,032 | upstream |
| `static/js/settings.js` | 5,823 | upstream |
| `static/app.js` | 4,800 | upstream + fork (camera, command menu, pull-refresh) |
| `routes/cookbook_routes.py` | 4,545 | upstream |
| `src/llm_core.py` | 2,990 | upstream + fork (think overrides) |

Two distinct costs, and this week demonstrated both:

1. **Navigation drag.** The verifier-switch hunt crossed four of these
   files; the settings route hiding inside `auth_routes.py` produced a
   guessed-wrong path that cost a deploy cycle.
2. **Cherry-pick conflict surface.** The fork's sync model is
   fast-forward + cherry-pick (history was rewritten; classic merges
   explode). Conflicts happen exactly where *both* sides edit the same
   file — and every fork feature we've inlined into `app.js`/`chat.js`
   is a standing conflict magnet for every future upstream patch to
   those files.

## The trap this design avoids

A bulk fork-side refactor of upstream-owned files would make their
patches unappliable (wrong paths, wrong context) — severing the
lifeline that delivered three fixes yesterday alone. Upstream is
ALREADY slicing on its own schedule: `tool_implementations.py` →
`agent_tools/*` with a re-export shim (the in-repo precedent that
preserved import paths), route-domain subpackages arriving
(document/webhook/vault came through 2026-08-10's sync), trackers
#4071/#3629, and #3266 for `agent_loop`. Racing them buys conflicts;
waiting costs nothing.

## Strategy — four rules

1. **Fork-owned code exits upstream-owned files.** The core of this
   QoL sprint. Everything WE wrote that lives inline in upstream
   monoliths moves to fork modules under an ownership-signaling home
   (`static/js/fork/`, `static/css/fork.css`), leaving one-line hooks
   behind. Candidates measured: command menu + camera + pull-refresh
   wiring (app.js), composer-lock reconcile (chat.js), the cmd-menu
   CSS block (style.css). Effect: upstream patches to those files stop
   colliding with our code — the conflict surface drops to the hook
   lines. Python already follows this rule (`thinking_controls.py`,
   `attachment_rehydrate.py`, `calc_eval.py` planned).
2. **Upstream-owned monoliths: wait and adopt.** Never pre-split files
   upstream is actively refactoring. Cherry-pick their slices greedily
   when they land (#3266 especially — it hits the file where most fork
   agent work lives; landing it EARLY into our tree is the plan, not
   pre-splitting).
3. **Additive-only growth** (standing rule, now written down): new
   features are new modules with contract tests. The monoliths get
   hooks, never bodies.
4. **Loud seams ride along.** The verifier saga's real lesson was
   silence, not size: the settings POST silently dropped unknown keys
   (now-registered key aside, it still drops others), and fork UI code
   swallowed a 404 in a bare catch. Phase 1: settings POST returns 400
   on unknown keys; settings writes surface failures as toasts; audit
   fork-written fetch handlers for swallowed errors. Doc-020's
   error-as-teaching principle, applied to our own seams.

## Phases

1. **Loud seams** (small, ships first): 400 on unknown settings keys +
   write-failure toasts + fork fetch-handler audit.
2. **Fork-code extraction**: `static/js/fork/{commandMenu,camera,
   pullRefresh,streamReconcile}.js` + `static/css/fork.css`; app.js /
   chat.js / style.css keep one-line hooks. Contract test: a grep
   tripwire asserting fork markers (cmd-menu ids, camera input, etc.)
   do not reappear as bodies inside upstream files.
3. **Adopt upstream slices** as they land; measure the sync-conflict
   rate before/after phase 2 — that number is this design's success
   metric, alongside "no gate regressions."

## Non-goals

- Splitting `email_routes.py`, `settings.js`, `cookbook_routes.py`,
  or the 41k-line `style.css` body: pure upstream churn territory,
  zero fork code inside them beyond phase-2 extractions. Their weight
  is upstream's debt; ours is only what we added.
- Any move that changes runtime behavior. This is a relocation, not a
  rewrite; the gate must stay green on every step.

## Decision log

- 2026-08-11 — Doc created after the three-bug verifier saga and the
  "is the app too bloated?" question. Diagnosis: silence at seams hurt
  more than size, but fork-code-in-upstream-files is a real and
  growing conflict tax. Strategy: extract ours, wait for theirs,
  grow additively, fail loudly.
