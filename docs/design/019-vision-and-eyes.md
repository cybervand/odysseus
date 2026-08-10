# 019 — Vision repair & giving models eyes

**Status:** Active (started 2026-08-10). Fix 1 shipped; roadmap below.

## Problem

Tool-gap analysis for "a good and sharp model" (2026-08-10) found the
inventory broad (73 tools) but blind: no way for a model to *see* — not
its own attached images after a reload, not the websites it builds, not
a screenshot. Three gaps, in priority order: **(1)** browser/screenshot
with multimodal critique, **(2)** `calc` (the doc-018 evaluator as an
agent tool), **(3)** agent-initiated image analysis. Per the fork rules,
upstream was surveyed before building.

## Upstream survey (2026-08-10)

- Image analysis is **known-broken upstream and unfixed**: #4723 (vision
  models can't see attachments), #5499 + #4249 (Ollama 400; "one failed
  image poisons the session"). Best triage (on #5499): **#5420**'s
  `persistable_message_content()` strips inline base64 from stored
  messages and `_parse_msg_content` never rehydrates the flattened form.
- **PR #5449** (`read_attachment` agent tool, owner-checked
  `odysseus://attachment/<id>` URIs) — reviewer called the security
  design sound; stalled on fixable perf issues (sync upload resolution
  on the event loop; per-attachment index writes); closed unmerged.
  Prime adapt candidate for gap 3.
- Upstream ships a **built-in Browser MCP server** (`builtin_browser`,
  npx-based) — observed failing to connect in our containers. Gap 1
  should start by investigating it before building anything.
- 14 new origin/dev commits; cherry-picked: #5829 (Qwen bare-end-marker
  pipe), #5727 (api_call SSRF pin), #5831 (memory-store overwrite guard).

## Fix 1 (shipped): reload hallucination — `src/attachment_rehydrate.py`

Live repro on the `odysseus-imgtest` container (prod image, fresh data,
gemma4:12b via Ollama):

- **Live turn: vision works.** `model_supports_vision` correctly gates,
  `build_user_content` attaches the data URL, gemma described a
  generated test image (red triangle / yellow circle / blue background)
  perfectly. #4723's total blindness does NOT reproduce on our stack.
- **Post-restart replay: confident hallucination.** With history
  flattened to `[Attachment: shapes-test.png | id=…]` text (the #5420
  storage form — confirmed in the DB), gemma *invented* "red circle,
  blue square, green triangle on white" — every detail wrong, derived
  from the filename. Worse than an error: silently plausible. Note the
  in-memory session masks the bug — it only fires after reload, which
  is why turn-2 tests kept false-passing until the test isolated
  restart + zero text leakage.

Fix: at call-assembly time (`build_chat_context`, non-incognito, vision
models only), walk recent history user messages whose
`metadata.attachments` list images but whose content is the flattened
string; re-resolve each upload owner-checked + path-confined; rebuild
multimodal content. Bounded: 4 most-recent images / 8 MB per call.
Storage stays lean (preserves #5420's intent). Verified live: the
reloaded session describes the real pixels. Commit `ebeac24a`; 8 unit
tests.

## Roadmap

1. **Browser/eyes (gap 1):** diagnose `builtin_browser` MCP (npx
   download at boot? missing toolchain tier?); if unusable, a headless
   chromium container on br1 + navigate/screenshot/console-errors tool.
   Then: screenshot → gemma4 critique closes the self-verification loop
   for built websites (doc 013 gauntlet family).
2. **`calc` tool (gap 2):** one-string-arg agent tool wrapping the
   doc-018 AST evaluator (unicode ops, comma/fragment guards). Smallest
   possible format surface for weak models; no FP problem — the model
   opts in by calling.
3. **`read_attachment` (gap 3):** adapt PR #5449 with the reviewer's
   fixes (move manifest resolution off the event loop, batch index
   writes). Gives agents access to chat attachments; composes with the
   rehydrator.
4. **Live lens (camera, stateless — no storage). v1 spec converged
   2026-08-10, two modes:**

   - **Snapshot mode (aim-and-ask):** live viewfinder at native fps
     with an in-browser detector (YOLO-nano/MediaPipe via WebGPU/wasm,
     15–30 fps on-phone — zero server GPU, labels track the live view
     perfectly) streaming class labels; the user presses **snapshot**
     and that exact frame goes to gemma4 with the standing prompt. The
     answer renders attached to the frozen frame (Polaroid panel, live
     view shrinks to a corner). Alignment honesty by explicit choice —
     the user picked the frame. Auto-trigger-on-steady is a later
     option, not v1.
   - **Synced mode (parked/tripod):** the display shows only the frame
     under analysis — camera throttled via the getUserMedia `frameRate`
     constraint (also the biggest battery saving) and/or the canvas
     renders the last sampled frame. Continuous narration; the screen
     IS the model's view, so display and analysis cannot disagree.
     Self-pacing: cadence = achieved processing rate.

   **Measured (2026-08-10, lean endpoint, Ollama native /api/chat,
   512px frame, `think: false`, num_predict 40, warm):**
   `gemma4:e2b` **0.52 s/frame → 1.9 fps** ("Triangle red, circle
   yellow." — correct); `gemma4:12b-it-q8_0` **1.24 s/frame →
   0.81 fps** (full correct sentence); `gemma4:e4b` **crashes
   llama-server on vision** (`GGML_ASSERT(n_inputs < GGML_SCHED_MAX…)`,
   Ollama v0.32.5 — retest after upgrading to ≥v0.32.6, user-held
   Unraid recreate). Two hard-won gotchas: **`think: false` is
   mandatory** — with thinking on, the whole token budget disappears
   into the reasoning channel and `content` returns empty; and the
   earlier 3–5 s estimate was chat-pipeline overhead, not the model —
   the lean endpoint is 3–6× faster. Consequence: E2B is the synced-
   mode workhorse (~2 fps), 12B the snapshot-mode describer (~1.2 s),
   and the in-browser detector tier is optional rather than
   load-bearing at these speeds.

   Shared: cadence dial caps each loop (requested-vs-achieved readout —
   also our latency instrument); drop-frames-never-queue; standing
   prompt; lean stateless frame endpoint (no session, no history, no
   persistence). Tier ladder behind it: (a) in-browser detector,
   (b) still-frame gemma4 via Ollama (measured above),
   (c) **temporal video via the lab transformers harness**:
   Gemma 4's native video input is timestamped frame sequences through
   `AutoProcessor` — transformers-only (Ollama hasn't shipped video
   input as of v0.32.6), so the virtual-experts-lab serving pattern
   extends to it (12B quantized, sharded, one lab experiment resident
   at a time); a sliding window of live frames stamped 00:00…00:25
   gives real temporal context today. Per-frame token cost
   undocumented — measure prefill before promising cadence. Blockers
   for the phone: getUserMedia requires HTTPS → the dead Tailscale
   sidecar needs a fresh TS_AUTHKEY (user-held). Wire-color-style
   readings are assistive only — never for live electrical work.

## Decision log

- 2026-08-10 — Upstream surveyed (nothing to pull; triage adopted);
  #5420 regression reproduced and fixed via additive rehydration
  module; three upstream commits cherry-picked; roadmap set: eyes,
  calc, read_attachment.
