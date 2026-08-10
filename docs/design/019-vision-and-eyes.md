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

1. **Browser/eyes (gap 1) — design (2026-08-10).** Finding: upstream's
   `builtin_browser` is the official **Playwright MCP**
   (`npx -y @playwright/mcp@latest --headless --caps vision`,
   `src/builtin_mcp.py`), already wired with a persistent cache
   (`data/local/playwright-mcp-cache` incl. `PLAYWRIGHT_BROWSERS_PATH`
   — on the mounted data volume, so it survives deploys) and an
   `ODYSSEUS_BROWSER_MCP_REQUIRE_CACHE` no-network mode. So this is an
   *enablement + bridging* project, not a build:
   - **Phase A (enable): ALREADY DONE IN PROD** (verified 2026-08-10
     post-vision1-deploy): `Built-in: Browser` connects with **30
     tools via stdio**, using the image's system chromium
     (`--executable-path /usr/bin/chromium --isolated --no-sandbox`) —
     no download, no cache priming needed. The imgtest failure was
     fresh-data cold cache only. The models have had a working browser
     all along; what's missing is only the bridge to their eyes.
   - **Phase B (the eyes loop):** `--caps vision` returns screenshots
     as MCP image content; bridge them into the upload store →
     attachment id → **vision injection** (shared mechanism with
     `read_attachment` below) → gemma4 critique. Console errors and
     DOM text come free from the MCP's existing tools.
   - **Guards:** browsing posture is the *inverse* of the api_call
     SSRF pin — the whole point is our own br1/LAN sites. Default
     allowlist: br1 subnet + registered server ports + user-named
     URLs; page lifecycle is per-turn (close everything; no persistent
     sessions in v1).
   - **Validation:** the doc-013 gauntlet website probes gain a
     "screenshot your own site and fix what you see" step — the
     self-verification loop the write-time health checks can't reach.
2. **`calc` tool (gap 2) — design (2026-08-10).** Vendor the doc-018
   evaluator into `src/calc_eval.py` (additive; the lab shim keeps its
   server-side copy — repo copy is canonical going forward and
   Strategy A imports it later). Tool-mode differences from the shim:
   the model opts in by calling, so there is NO hijack/FP risk — which
   safely unlocks a **scientific tier**: AST-whitelisted `ast.Call` to
   `math.{sqrt,sin,cos,tan,log,log2,log10,exp,floor,ceil,fabs}` plus
   `pi/e/tau` names. Keep unicode/comma normalization (paste
   robustness). **New and mandatory — in-process resource guards** the
   shim never needed as a container PID 1: exponent/operand digit caps
   (reject `**` beyond ~10k digits), result magnitude cap, AST depth
   cap — a calc tool that can hang the app on `9**9**9` is a denial of
   service, not a calculator. Schema: `{expression: string}` →
   `{result, formatted, error?}`; errors teach ("`sqrt` needs
   parentheses: sqrt(2)" — composes with doc 020 help). Tool-index
   wording steers weak models python→calc for pure arithmetic.
3. **`read_attachment` (gap 3) — design (2026-08-10).** Adapt PR
   #5449 keeping its reviewed-sound core (owner-checked bounded
   manifest, stable `odysseus://attachment/<id>` URIs, no filesystem
   paths, no cross-owner or admin bypass) and applying exactly the
   reviewer's asks: manifest resolution via `asyncio.to_thread` (a
   20-candidate rebuild blocked the loop 0.4 s), **one batched index
   write** per reconstruction (was 20), regression tests for
   loop-responsiveness and batched lifecycle writes. Our addition —
   the piece #5449 lacked: **vision injection**. For image attachments
   on vision-capable models, the tool result carries a marker and feed
   assembly injects the actual image block via the rehydrator
   machinery (ebeac24a); text-only models get the cached VL
   description. This makes "bytes → attachment → model eyes" ONE
   pathway shared by chat uploads, browser screenshots (item 1), lens
   snapshots a user promotes to chat, and future camera_snapshot.
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
   `gemma4:e2b` **0.51 s/frame → 2.0 fps** ("Triangle red, circle
   yellow." — correct; active footprint only **1.7 GB** — co-resides
   with anything); `gemma4:e4b` **0.62 s/frame → 1.7 fps** (4.4 GB
   active; crashed llama-server on v0.32.5's vision path
   [`GGML_ASSERT(n_inputs…)`] — **fixed by the 2026-08-10 upgrade to
   v0.32.6**); `gemma4:12b-it-q8_0` **1.22 s/frame → 0.82 fps** (full
   correct sentence, 14 GB resident). Three hard-won gotchas:
   **`think: false` is mandatory** — with thinking on, the whole token
   budget disappears into the reasoning channel and `content` returns
   empty; the earlier 3–5 s estimate was chat-pipeline overhead, not
   the model — the lean endpoint is 3–6× faster; and **load order
   matters** — a model loaded while VRAM is scarce keeps its degraded
   CPU/GPU split (12B: 3.0 s at 21% CPU) until *explicitly unloaded and
   reloaded* — evicting the other models does not rebalance it. The
   lens must load the big model first or stop/start on mode switch.
   Consequence: E2B is the synced-mode workhorse (~2 fps), E4B the
   quality-vs-speed middle rung, 12B the snapshot-mode describer
   (~1.2 s), and the in-browser detector tier is optional rather than
   load-bearing at these speeds.

   **Model lifecycle (2026-08-10): vision models load only while the
   lens is up.** Open → immediate warmup ping (load hides behind the
   aiming moment; "warming up" indicator — colds measured 18–88 s cold
   page cache, seconds warm); every frame carries a rolling
   `keep_alive` (~10 min); close → `navigator.sendBeacon` on page-hide
   hits an unload endpoint (`keep_alive: 0`); server-side idle timer
   unloads regardless if frames stop (a crashed tab must not squat on
   a card). Chat vision is already load-on-demand via Ollama — this
   policy is for the lens's continuous modes. Same rule as the doc-018
   contention protocol: nothing holds VRAM without an active reason.

   **Settings — new "Vision" group** (extends existing
   `vision_enabled`/`vision_model` keys in `src/settings.py`):
   `lens_synced_model` (default e2b), `lens_snapshot_model` (default
   12b), `lens_max_fps` (2/1/0.5/0.2/manual), `lens_output_tokens`
   (40), `lens_frame_resolution` (512), `lens_image_token_budget`
   (lab-only until Ollama exposes it), `lens_keepalive_minutes` +
   `lens_unload_on_close`, `lens_standing_prompt`.

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

5. **Verifier vs. vision (2026-08-10, user-spotted):** the completion
   verifier is text-only by design (cold context, action record) — it
   cannot check image-grounded claims and could fail correct visual
   answers or invent its own image, burning re-verify rounds. Shipped
   immediately: an epistemic-humility rule (visual requirements =
   unverifiable → plausible-action-counts-as-MET, never guess pixels).
   Roadmap: **vision-injected verification** — when the task hinges on
   an image and a vision model is available, attach the actual image
   blocks to the verifier call (the ebeac24a injection machinery);
   verifier conflicts stay process-flags to the agent, never
   user-facing truth. Related teaching gap: gemma4:e2b asked for an
   "OCR tool" that deliberately doesn't exist — all three gemmas
   advertise `vision`+`tools` in Ollama and read text in images
   natively; a doc-020-style teaching line for vision-capable agent
   models ("you have eyes; read the image directly") closes it.

## Decision log

- 2026-08-10 — Upstream surveyed (nothing to pull; triage adopted);
  #5420 regression reproduced and fixed via additive rehydration
  module; three upstream commits cherry-picked; roadmap set: eyes,
  calc, read_attachment.
