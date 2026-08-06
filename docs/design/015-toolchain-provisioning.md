# 015 — Toolchain provisioning: manage_framework and the persistent tier

**Status:** Shipped (901370da, deployed toolchain1/v63 2026-08-06) — layers 2-4; layer 1 blessed-set Dockerfile pass rides the Node 22 bump

## Problem

Frameworks installed by models die with the container. The container FS is
ephemeral; only `/app/data` (the volume) survives a deploy. Observed:

- flask, pip-installed into system site-packages, vanishes on EVERY image
  swap — the deploy chain carries a standing `pip install -q flask` +
  relaunch step as a manual antidote (2026-08-05 onward).
- Models `npm install -g` / `pip install` into the doomed tier because
  that is the trained idiom (ritual gravity, doc 009/013): the command
  succeeds, the work persists until the next deploy, then silently breaks.
- A framework installed in one chat is invisible to every other chat even
  while it exists: nothing tells the next model what is already available,
  so it re-installs (slow, network-bound) or worse, assumes absence and
  hand-rolls a substitute.

The industry mostly deletes this problem instead of solving it: Emergent /
Lovable / v0 bake ONE blessed stack into a golden image and never install
at runtime; E2B-style platforms give every session a throwaway sandbox
where global state cannot exist; Replit makes the environment declarative
(Nix). Odysseus is deliberately a single shared persistent world — closest
to Replit in spirit — so it needs the declarative-ish answer, sized for a
homelab.

## Decision

Four layers, each catching what the one above misses:

1. **Blessed set in the image** (Dockerfile): the frameworks the prompt
   ladder proves out (vite, tailwind, react scaffolding, flask) are
   preinstalled and prompt-taught as "already installed — do not install".
   Weak-model-friendly: no discovery, no decision. Graduation into the
   blessed set is driven by the model-capability database (doc 013).

2. **Persistent prefixes** (env, substrate for everything below): global
   npm and user pip land on the volume, so even untaught installs survive
   deploys and are shared across chats by construction:
   - `npm config set prefix /app/data/toolchain/npm` (+ its `bin` on PATH)
   - `npm config set cache /app/data/toolchain/npm-cache` — shared warm
     cache; the second chat to install anything gets it in seconds
   - `PYTHONUSERBASE=/app/data/toolchain/py`, `PIP_CACHE_DIR=/app/data/toolchain/pip-cache`
   - Per-PROJECT deps stay per-project (`node_modules`, project dirs on
     the volume) — sharing is for CLIs and caches, never for a project's
     dependency tree, so one chat can never version-break another's app.

3. **`manage_framework` tool** (the taught verb — same pattern as
   manage_server, doc collapsing a botchable ritual into one action):

   ```manage_framework
   {"action": "install", "name": "tailwindcss"}
   ```

   Actions: `install`, `upgrade`, `remove`, `list`, `info`. Optional
   `version` pin on install/upgrade (`{"action": "upgrade", "name":
   "vite", "version": "7.1"}` → the framework itself is editable, not
   just addable). The tool resolves the HOW so the model never does:
   known-set lookup first (curated name → manager/package map), then
   registry probe (npm view / PyPI) for unknowns; installs to the
   persistent tier; verifies the binary actually answers (`vite
   --version`) before reporting success; records to the manifest.
   Unknown-name resolution is shown honestly ("installing `@sveltejs/kit`
   for 'sveltekit'") — model typos and hallucinated package names are a
   supply-chain surface; every install is logged where the human can see
   it. v1 is npm + pip ONLY; anything needing root/apt returns a clear
   "ask the human" error (app runs uid 99; also the safety-correct tier).

   **No location parameter, by design.** Location is the decision models
   get wrong (the doomed-tier lesson), so the tool removes it: the shared
   tier has exactly one right place and the tool owns it. Project-scoped
   deps flow through bash, which already runs in the session's cwd via
   the session context — the model's location arrives automatically, the
   same way session_id reaches every tool. (Contrast manage_server's
   explicit `cwd`: WHICH app a server belongs to is genuinely the
   model's knowledge; WHERE shared tools live is system knowledge.) If a
   `scope: "project"` action is ever added, it defaults to the session
   cwd like bash — model says nothing, override optional.

4. **Manifest + context line** (the memory and the discovery):
   `/app/data/toolchain/toolchain.json` — name, manager, version, when,
   session. Written by the tool on every action. Two consumers:
   - boot reconciler: after an image bump breaks an ABI-tied wheel, a
     startup pass reinstalls what the manifest says should exist
     (self-healing, same spirit as servers.json restart)
   - agent context: a generated line — `toolchain: vite 7, tailwind 4,
     flask, svelte` — injected like the cwd line, so every chat KNOWS
     what is installed. Disk visibility without prompt visibility is
     only half of "other chats can use it".

Companion bash guard (same teach-by-refusal as `_server_command_guard`):
`npm install -g` and `npm i -g` in bash are refused with directions to
manage_framework. Plain project-local `npm install` stays allowed — that
is the correct default and models do it fine. The line taught in
TOOL_SECTIONS: "library for THIS project → npm install in the project;
tool available EVERYWHERE → manage_framework."

## Rejected alternatives

- **Golden-image-only (the Emergent model).** Handles zero runtime
  framework requests; every new need is a human rebuild. Its real lesson
  (constrain weak models to a blessed path) is kept as layer 1.
- **Per-session sandboxes (the E2B model).** Deletes shared state rather
  than managing it — directly opposed to the product goal of a persistent
  world models build up across chats; also heavy for a 32 GB homelab.
- **Nix (the Replit model).** The theoretically-correct shared immutable
  store; operationally far too heavy here, and weak models cannot drive
  it.
- **`install_framework` (install-only tool).** Naming/scoping rejected in
  design: version moves (upgrade/downgrade/pin) and removal are the same
  lifecycle with the same gotchas — one manage_* verb, house style.
- **Auto-recording bash installs into the manifest.** Parsing arbitrary
  bash output for "what got installed" is guesswork; instead the env
  makes untaught installs *survive* (safety net) while the tool remains
  the taught path that *records*.
- **apt tier in v1.** Needs root from a uid-99 app; system packages are
  where install-anything becomes a real attack surface. Routed to the
  human instead.

## Validation

(When built:) unit tests over resolver + manifest ops with a monkeypatched
runner; bash-guard tests (global refused with pointer, project-local
allowed); persistence acceptance: install tailwind in chat A → deploy →
`tailwindcss --version` answers in chat B with no reinstall, context line
lists it; the deploy chain's flask step deleted and the lodge still comes
up after a swap.

## Open items

- Everything (doc precedes build). Build order: layer 2 env prefixes →
  retire the deploy-chain flask hack → tool + guard + manifest → context
  line → boot reconciler → blessed-set Dockerfile pass (fold into the
  pending Node 22 bump).
- Disk watermark: toolchain + caches on the volume should surface in
  `get_workspace` sizes eventually.
- Runtime binaries (Node itself, Python itself) stay image-tier by
  design; version bumps ride the Dockerfile.

## Decision log

- 2026-08-06 — designed (this doc), after the flask-reinstall hack and
  the manage_server/stale-process arc made the pattern obvious; named
  manage_framework over install_framework to cover the full lifecycle.
- 2026-08-06 — shipped 901370da, deployed toolchain1/v63. Acceptance
  held: deploy chain carried NO flask step; flask entered the tier via
  toolchain.install() as uid 99, skilodge relaunched through the registry
  resolving flask from the volume, restaurant 200. Manifest keys are
  canonical package names (aliases collapse). Deploy-chain flask hack
  retired in the runbook memory.
- 2026-08-06 — GUARD-AS-TEACHER VALIDATED live with gpt-oss:20b (the
  weakest agent-capable model in the fleet). manage_framework was
  deliberately absent from its toolbox (not in ALWAYS_AVAILABLE, Chroma
  index predates it). Natural-phrased request ("typescript available on
  this whole machine") → model tried `npm install -g` → guard refused
  with the JSON shape → model's own thinking: "Need manage_framework?
  It's not listed but 'manage_framework' mentioned. Use that:
  action='install', name='typescript'." → correct call, typescript in
  the tier, manifest + context line updated, hello.ts compiled and ran.
  Conclusion: the bash guard IS the discovery channel for this tool —
  it fires exactly when relevant, teaching lazily instead of spending
  always-on prompt space. ALWAYS_AVAILABLE promotion unnecessary for
  now; revisit only if a model ignores the guard's teaching.
