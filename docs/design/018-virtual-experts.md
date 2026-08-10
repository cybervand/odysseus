# 018 — Virtual Experts for gpt-oss-20b (research track)

**Status:** Draft (supersedes the user's external `virtual-experts-design.md`
v0.1; revised 2026-08-08 after transcript + source-code investigation)

## Problem

gpt-oss-20b is a 24-layer MoE (32 experts/layer, 4 active, ~3.6B active of
21B). Its routers classify the task ("this is multiplication") as early as
layer 0 — a free per-layer classifier. Chris Hay's "Mixture of Experts,
Plus One" demo claims to exploit this by replacing neural experts with
deterministic code (a Python math expert), pruning the model from ~16GB to
~8.7GB while *improving* arithmetic. If the mechanism is real, it is a new
primitive: deterministic computation presented to the architecture as an
ordinary expert, with no tool-call round trip. The original draft planned
to port his MLX implementation to PyTorch/CUDA on this stack.

## What the investigation changed (read this first)

**The reference implementation does not implement the video's claim.**
Verified 2026-08-08 by reading `chrishayuk/chuk-lazurus`
(`src/chuk_lazarus/inference/virtual_experts/wrapper.py`):

- Generation runs **unmodified** — every layer executes normally; every
  token is argmax of the model's own logits. The "virtual routers" are
  pure **observers** scoring hidden states against calibrated directions;
  they never redirect computation.
- The math answer comes from `MathExpertPlugin.extract_and_evaluate`,
  which regex-parses the arithmetic **from the prompt string** and
  safe-evals it in Python, independent of generation.
- `solve()` then picks which answer to PRESENT: if the observers voted
  "math" (`used_virtual`), the Python string is returned and the model's
  text is discarded (wrapper.py ~486–513). **Answer substitution keyed on
  router observation — neither hidden-state injection nor constrained
  decoding.**
- The newer "CoT/Rogue-1" path has the *model emit a YAML action* that is
  dispatched to the plugin — i.e., tool calling with different
  serialization.
- The video's narration confirms the hand-wave (auto-transcript on file):
  the injection step is described only as "run a bit of a calibration so
  the routers know to handle the math"; the pruned demo is attributed to
  "just retraining the router" while the live demo used the hijack.

**What IS real and worth porting:** the calibration method (directional
probes in activation space from positive/negative example prompts, per
layer — this produces the genuine early-layer classification heatmaps);
the plugin registry shape (`can_handle` / `execute` /
`get_calibration_prompts`, see also his separate `virtual-experts` repo
with arithmetic/time/weather/mcts plugins); `SafeMathEvaluator`
(AST-whitelisted eval); and the pruning work (repo dir `gpt-oss-lite-v2`,
unread as of this draft).

**Consequence:** this project is an *invention*, not a port. Our Strategy
A (below) would be the first version of the idea that actually lives in
the decode path.

## Decision

Build in phases on **copperwarehouse only** (the two-machine plan is
dropped), with an explicit kill criterion, toward two deliverables: a
router-informed **constrained-decoding** math expert (Strategy A, the
first real implementation of the claim), and a **pruned single-card**
gpt-oss variant.

### Target environment (single box — replaces original §4)

- copperwarehouse: Unraid 7.3, Ryzen, **32 GB RAM**, **2× RTX A2000 12 GB
  (no NVLink)** — verified idle at time of writing.
- **No CPU fallback exists on this box.** The transformers CPU path
  dequantizes MXFP4 toward bf16 (~40+ GB) which fits neither RAM nor
  VRAM. Everything runs on the GPUs with quantized kernels,
  `device_map="auto"` sharded across both cards.
- **O1′ (first thing Phase 1 must prove):** MXFP4 triton kernels actually
  run on Ampere (SM 8.6) with the pinned transformers/triton versions.
  If not, fallback is 8-bit bitsandbytes (~21 GB, still sharded) — NOT
  CPU.
- The HF safetensors are a separate ~13 GB pull to `/mnt/cache/LLms`
  (1.4 TB free); the existing Ollama GGUF blob cannot be reused.
- **GPU contention protocol:** qwen occupies both cards when loaded.
  Research sessions start with `ollama stop <model>`; experiments run in
  a Docker container (`--gpus all`) so teardown is `docker rm`, never a
  leaked process squatting on VRAM. The existing RAM cap + reclaim cron
  protect the host side.
- **llama.cpp/Ollama can never serve the wrapped model** (no router
  hooks). Serving happens via a thin FastAPI `/v1/chat/completions` shim
  around the PyTorch process — which Odysseus already knows how to adopt
  (own br1 IP, model-endpoint registration, `supports_tools=1`,
  cookbook `adopt_served_model`).

### Strategy ladder (replaces original §5.4)

- **Strategy 0 (reference behavior):** answer substitution outside
  generation. Useful only as a baseline to beat; implementing it teaches
  the calibration port.
- **Strategy A (v1 target):** router-informed **constrained decoding** —
  when calibrated observers cross threshold θ, compute the answer once,
  then force the digit sequence through logit masking. Correctness from
  the decoder; the MoE observation contributes early, cheap, per-layer
  detection. This exceeds the reference.
- **Strategy B (research stretch):** hidden-state encoding — learn a
  projection from answer strings into the hijack layer's residual
  subspace so downstream layers verbalize it. Unimplemented anywhere,
  including the reference. High risk, high novelty.

### Kill criterion

If wrapped Strategy A performs no better than an *unwrapped* prompt-level
classifier + the same constrained decoding — on the arithmetic suite, the
regression suite, AND the false-positive probe — the router observation is
dead weight and gets removed. The remaining project is still worth having
(deterministic math + pruning), but we stop pretending the MoE part earns
rent. Measured, not vibes.

### Phases (revised)

1. **Introspection + kernel proof (1–2 evenings, GPU-sharded).**
   Vendor the calibration/introspection modules, pull HF weights, prove
   O1′, reproduce per-layer classification heatmaps on math AND
   agent-shaped prompts (see "second expert" below). Read
   `gpt-oss-lite-v2` to answer how pruning was actually done.
2. **Strategy A wrapper (1–2 weekends).** Port calibration to
   transformers/CUDA; implement compute-once-at-detection +
   logit-masked verbalization (never per-token/per-layer interpreter
   calls). Deliverable: `127 * 89 = 11303` exactly, with the kill
   criterion measured.
3. **Pruning (1 weekend).** Activation-frequency logging over a mixed
   corpus; drop cold + math experts; target ≤9 GB. **On this box that is
   the difference in kind: the pruned model fits ONE A2000 with KV
   headroom, leaving the other card for qwen — both worlds resident,
   no contention protocol needed.** Note O4 (router remap vs zero-out
   under MXFP4) and check whether pruning requires router *retraining*
   (per the video's narration) — if so, Phase 3 inherits a training step.
4. **Registry + Odysseus integration (open-ended).** Serving shim, br1
   IP, endpoint registration. Candidate second expert — and for THIS
   fork the higher-value one: **tool-call format validity** (grammar-
   constrained JSON at emission time). Every gauntlet failure family this
   week (harmony arg mangling, pluralized tool names) is a format failure
   at the moment of highest structure; Strategy A's machinery is exactly
   the cure. Math is the tracer bullet; tool-call validity is the
   payload.

### Boundary (new non-goal)

Virtual experts absorb only **deterministic, side-effect-free
computations that fit inside a forward pass**. Anything with IO — files,
servers, network — stays in the agent loop. This complements the doc
001–017 harness; it does not replace it.

**The guarantee, stated precisely (2026-08-10, after the user probed
with the Einstein field equations in ASCII):** "can't be arithmetically
wrong" does NOT mean "solves any math expressed in ASCII" — that is
impossible for any system, not just ours (Richardson's theorem: even
equality of elementary symbolic expressions is undecidable). The
deliverable guarantee is narrower and therefore real: **every numeric
digit the model commits to is computed, never sampled** — numeric
claims are exact or absent. The model remains free to be wrong about
physics, modeling, and symbol-pushing; those are not arithmetic errors.
`G_mu_nu + Lambda*g_mu_nu = …` correctly routes neural (identifiers,
verified live — the FP guards ARE the boundary enforcement); its
numeric endpoints (`2*6.674e-11*1.989e30/299792458**2` → 2953.99 m,
solar Schwarzschild radius) compute instantly today. Expert admission
test distilled for any future plugin: **crisp trigger + canonical
answer + zero false positives.** Arithmetic passes all three maximally;
computer algebra (sympy — rearranging, differentiating, Christoffel
symbols for a given metric) passes determinism but strains trigger
(wall-to-wall identifiers) and canonicality (simplification is
choice-laden) — a candidate expert, admitted only if it can pay the
same FP bar; proof assistants verify rather than answer; the rest is
judgment and stays neural.

## Phase 1 findings (2026-08-08 — completed in one evening, as budgeted)

Lab: container `virtual-experts-lab` on copperwarehouse (pytorch image +
torch 2.9.1/cu126 + transformers 5.14 + kernels **0.15.2** + gcc for
triton JIT). Model: HF safetensors at `/mnt/cache/LLms/hf`. Probes in
`/mnt/user/appdata/virtual-experts/`; raw data `/lab/heatmap.json`.

- **O1′ PASS.** MXFP4 loads *quantized* (Mxfp4Config intact) sharded
  across both A2000s: **5.93 + 7.84 GB**, 12 s load, generation works
  (~1.7 tok/s via transformers — research-grade, as expected). Ampere
  sm86 is officially supported (`compute_capability >= (7,5)` in the
  quantizer gate). Environment landmines for the record: pytorch:latest
  image ships torch 2.2 (upgrade), torch 2.13+cu130 bleeding edge causes
  illegal-memory-access on load (pin 2.9.1), `kernels` must satisfy the
  window `0.15.2 ≤ v < 0.16.0`, and triton JIT needs a C compiler the
  runtime image lacks.
- **Baseline reproduced verbatim:** stock model answers `127 * 89 =`
  with *" 11263. So 11263 is prime? Let's check:"* — the exact wrong
  answer and prime-check spiral from the video, on our hardware.
- **Math is a real router-level class.** Within-family top-4 Jaccard
  across four different arithmetic prompts: **0.6–0.8 at most layers**,
  vs math↔neutral ≈ 0.0–0.3 and math↔false-positive **≤ 0.17 nearly
  everywhere**. The routers separate math from neutral prose from layer
  0 (zero shared top experts at L0) — Hay's early-classification claim
  is quantitatively confirmed here.
- **The false-positive problem is largely pre-solved.** Phone numbers,
  "Boeing 747", version strings, addresses route almost entirely unlike
  real math at every layer (one blip at L16). Calibrated probes inherit
  this discrimination for free — de-risks the §7 probe suite
  substantially.
- **O5: qualified yes.** Deliberately heterogeneous agent-shaped prompts
  (JSON fragment / prose intent / TOOL CALL text / command line) agree
  ~0.2–0.5 within-family — weaker than math's ~0.7, but well above
  agent↔neutral (~0.15) — and **converge to 0.8 at layer 23**. Agent
  context is detectable in routing space; a tool-call-validity expert
  should calibrate on homogeneous emission-context prompts and read
  late layers (or L16+). Hook detail that cost an hour: the MXFP4 fast
  path computes router logits via `nn.functional.linear` directly — the
  router module never fires forward hooks; hook the **MLP pre-forward**
  and recompute logits instead.
- **O3 informed:** separation exists from L0–L2, so an early-layer
  hijack subset is viable for math; agent detection favors late layers.

## Strategy-0 serving shim (2026-08-09 — Phase 4 seed, one evening)

Strategy 0 is now a served, picker-visible model. Canonical script:
`/mnt/user/appdata/virtual-experts/serve_virtual.py` (server-side, like
the Phase 1 probes); container `virtual-experts-lab` recreated with the
shim as PID 1 (`python serve_virtual.py`, host port **8899** published).
**Lifecycle = contention protocol:** `docker start virtual-experts-lab`
→ serving (~15 s model load); `docker stop` → GPUs free for Ollama.
Never both loaded at once.

- **Registered in Odysseus:** `model_endpoints` row `7dbad75c`
  (`virtual-experts-lab`, `http://192.168.1.113:8899/v1`, kind=local,
  shared, `cached_models=["math-expert"]` pre-filled). Inserted via
  `docker exec -u 99` DB write (no pinned `ODYSSEUS_INTERNAL_TOKEN` in
  the prod container, so the admin HTTP route isn't callable
  out-of-band). Reachability verified from inside the odysseus
  container. No `supports_tools` — chat-only research artifact; the
  shim ignores tool definitions.
- **Math path:** last user message → regex candidate → AST-whitelisted
  eval → instant substituted answer, honestly labeled *"computed by the
  Python virtual expert"*. `127 * 89` → **11303** exact (stock model:
  11263, reproduced Phase 1). Works streaming and non-streaming.
- **Good-faith baseline rules** (this is the kill-criterion comparator,
  so it must be reasonable, not a strawman): expression needs two
  numbers joined by an operator; unspaced hyphen chains (`555-1234`,
  `747-8`, `2026-08-09`) are identifiers, not subtraction. Smoke-tested:
  "Boeing 747-8" and a phone number both route to the neural path.
- **Neural path is harmony-aware:** generation decodes with special
  tokens intact and splits channels — analysis/commentary stream as
  `reasoning_content` (Odysseus renders it as thinking;
  `llm_core` reads that field for both stream and non-stream), final
  channel as `content`. Multi-token channel headers are held back
  (48 chars) so a half-arrived `<|channel|>final<|message|>` never
  leaks into visible text. `reasoning_effort` passes through
  (default low). transformers 5.x gotcha for the record:
  `apply_chat_template` returns a `BatchEncoding` — pass
  `**enc` to `generate()`, not the object positionally (the v1 shim
  crashed exactly there).
- **Perf observed:** short generations ~8–10 tok/s end-to-end on the
  sharded A2000s (Phase 1's 1.7 tok/s figure came from long-generation
  probe conditions). Research-grade either way, as the doc promises.

### Hardening after first real picker use (2026-08-09, same evening)

The user's first real prompt (`55×123=`) hung for minutes and exposed
three defects the curl smoke tests couldn't:

- **Unicode operators.** `×` is not `*`; the math path never fired and
  the prompt fell through to generation. Fixed: normalize `× ÷ − · ^`
  (and fullwidth forms) before detection. ASCII `x` deliberately stays
  an identifier — "1920x1080" and "4x4" must not become arithmetic.
- **Eager attention OOMs at real prompt sizes.** Odysseus sends a
  multi-thousand-token system prompt; eager attention materializes the
  full attention matrix and spiked 1.12 GiB over GPU 1's headroom.
  **On the A2000s, eager is also the only implementation that works:**
  sdpa raises (GptOss attention sinks unsupported in transformers
  5.14), and flex_attention compiles a triton kernel requiring 144 KB
  shared memory vs sm86's 99 KB hard limit (`No valid triton configs`).
  Mitigation: head+tail prompt truncation to 1536 tokens (512 head
  keeps the harmony system header intact) + `expandable_segments`
  allocator. Verified with a 7362-token prompt. Flex-on-sm86 block-size
  tuning is a possible future unlock; not worth it for Strategy 0.
- **Generation-thread death hung the SSE stream.** The OOM killed the
  `generate()` thread; `TextIteratorStreamer` never signaled end, the
  stream stayed open, and the picker spun on "Processing request"
  forever. Fixed: exceptions propagate — `streamer.end()` releases the
  consumer and the error renders as visible ⚠ text in chat;
  non-stream returns an OpenAI-shaped 500. Plus `[req]` log lines
  (path/prompt_toks/truncation) so the next diagnosis reads one line
  instead of a traceback.

Retest after fix: `55×123=` instant exact **6765**; 7362-token prompt
generates cleanly in 6.5 s; Boeing 747-8 still routes neural. Honest
framing for the picker: the *neural* path on real prompts is slower
than Ollama's gpt-oss and always will be on this serving stack — the
instant-exact math path (and later Strategy A) is the point.

### Capability edge probed (2026-08-09, "can it do orbital equations?")

Live probes found a **new false-positive class: expression fragments.**
Scientific notation (`6.674e-11 * 5.972e24 / 6771000`) split at the
letter `e` and the evaluator confidently answered the fragment
`24 / 6771000` — a wrong answer labeled exact, the worst failure this
project can produce. Fixed by admitting `eE` to the expression regex
(ast parses `6.674e-11` natively; bare sci numbers still don't trigger
— the operator gate holds) and allowing a leading `(` so
`(GM/r)**0.5` forms match (ast rejects unbalanced garbage). After the
fix, `(6.674*10**-11 * 5.972*10**24 / 6771000)**0.5` returns
**7672.3 m/s instantly** — numerically-written orbital mechanics works.
**Add "expression fragments" to the §7 FP suite** alongside Boeing/
phones/dates: any future evaluator extension re-risks this class.

Second fragment vector, same evening: **decimal commas.** The user is
Norwegian; `128,748 / 56` split at the comma and would have answered
`748 / 56` — locale-triggered, not notation-triggered, otherwise the
identical failure. And `128,748` is unrecoverably ambiguous (NO decimal
= 128.748, EN thousands = 128748), so the guard *rejects* rather than
guesses: candidates glued to a digit-comma boundary never evaluate —
they route neural. Period-decimals compute; comma-decimals get the
network. FP-suite rule distilled from tonight: **when the surface form
is ambiguous, don't fire — a false negative costs speed, a false
positive costs a wrong answer labeled exact.**

Honest capability map as shipped: literal numeric arithmetic incl.
powers, parens, sci-notation — yes, instant, exact. Functions (sqrt,
trig, log), constants (G, π), symbols, units, rearranging, word
problems — no; those route to the neural path like any prose. A
scientific-calculator upgrade (whitelisted `math.*` calls + named
constants) is a contained evening; symbolic algebra (sympy) is a
different beast and widens the FP surface — decide only after
Strategy A exists.

### Word problems: the trigger moves to the decode stream (2026-08-09)

Asked "how do we combine this with a natural-sounding word problem?"
(mixed-unit acceleration problem), the answer fell out of a live
transcript: the prompt contains **no literal expression** (bare numbers,
no operators — Strategy 0 correctly routes neural), but the model's own
*analysis channel* is full of them — it wrote `80*1.609=128.72`,
`a=(v²-u²)/(2s)`, `t=(v-u)/a`, having translated the words into physics
unaided (it even converted mph→km/h correctly and flagged the problem's
ambiguity in its final answer). Every `=` it emits is sampled tokens,
though — each one a silent-flub site.

**Design consequence for Strategy A:** the detector must run on the
*emission stream*, not just the prompt. When generated text ends with
`<expr>=`, pause decode, AST-eval the expression, force the exact digit
tokens, resume neural. Division of labor: language → formula is the
network's job (ambiguity, units, physics model); formula → digits is
the expert's. The expert never parses prose. Precedent: GSM8K
calculator annotations (`<<100/56=…>>`) and Toolformer — known-good
pattern; our fork's addition remains the router gate (observers arm the
interceptor cheaply per-layer; the kill criterion measures whether that
gate earns rent over an always-armed regex). Prompt-side substitution
(today's shim) stays as the fast path for bare arithmetic.

## Rejected alternatives

- **Porting the reference as-is** — it does not contain the mechanism
  (see investigation); Strategy 0 is a baseline, not a product.
- **Full-precision or Q8 26B-class models on this box** — 52 GB / 28 GB
  against a 19–20 GB cap; the July 51-GB livelock (14 h hard reset) is
  why the cap exists and stays.
- **Two-machine split (nygaard for CPU work)** — dropped by the user;
  single-box with GPU-only paths is simpler and honest about the 32 GB
  RAM ceiling.
- **Router retraining as v1 method** — valid (the video's pruned demo
  apparently used it) but breaks the cheap-iteration property; revisit
  only if Phase 3 forces it.

## Validation

Original draft's suites stand: 500-problem arithmetic suite (exact
match), ~100-prompt regression suite, false-positive probe ("Boeing
747", phone numbers, dates, version strings — the most important suite
in the project), perf/memory table stock vs wrapped vs pruned. Framing
correction: on this stack the project is a **correctness and
architecture** experiment — transformers decode on sharded A2000s will
not beat Ollama wall-clock, and the doc should never promise it.

## Open items

- O1′: MXFP4 triton kernels on Ampere — Phase 1 gate.
- O2: **ANSWERED** (2026-08-08): reference implements answer
  substitution; neither injection strategy exists anywhere. We invent.
- O3: hijack/observe all 24 layers vs early subset — Phase 1 heatmaps
  decide.
- O4: pruning remap vs zero-out under MXFP4. **Half-answered
  (2026-08-08, `gpt-oss-lite-v2/build_minimal_lite.py`):** the reference
  prunes by static frequency selection + tensor slicing — NO retraining
  anywhere in code ("just by retraining the router" was loose
  narration), and Hay's own README documents the resulting degradation
  ("2+2=" → "3" on the 16-expert build; missing attention biases noted
  as a known defect). The lite+virtual demo's math correctness comes
  entirely from answer substitution. Our Phase 3 quality bar must beat
  static frequency selection or accept the same degradation.
- O5 (new): do agent-shaped prompts ("about to emit a tool call")
  classify as crisply as arithmetic? Decides the tool-validity expert.
- O6 (new, 2026-08-09): emission-time interception mechanics for
  Strategy A — pause-at-`=`, compute, force digits, resume. Needs a
  custom LogitsProcessor or manual decode loop (transformers `generate`
  has no mid-stream pause/rewrite); decide during Phase 2. The stream
  detector must reuse the FP guards (fragments, hyphen chains).
- Note: repo is spelled `chuk-lazurus` (URL) with package
  `chuk_lazarus` — both spellings are "correct."

## References

- User's original draft: `virtual-experts-design.md` v0.1 (external).
- Chris Hay, "Mixture of Experts, Plus One" (youtu.be/-Mb8V2Usk6E);
  auto-transcript archived in session scratchpad 2026-08-08.
- github.com/chrishayuk/chuk-lazurus — esp.
  `inference/virtual_experts/wrapper.py` (the solve() verdict),
  `gpt-oss-lite-v2/` (unread).
- github.com/chrishayuk/virtual-experts — plugin registry ecosystem.
- OpenAI gpt-oss model card (arXiv:2508.10925); DeepSeekMoE
  (arXiv:2401.06066).

## Decision log

- 2026-08-09 — Strategy-0 shim built, served, and registered: harmony-
  split OpenAI shim as the lab container's main process on :8899,
  endpoint `7dbad75c` in the model picker. Baseline is now a usable
  chat model; Strategy A (Phase 2) is next and inherits the serving
  plumbing unchanged.
- 2026-08-08 — Doc created from the user's v0.1 draft + investigation:
  single-box revision (no CPU fallback, contention protocol, pruned-fits-
  one-card endgame), transcript + source verdict (O2 answered: reference
  is answer substitution — we invent, not port), strategy ladder with
  kill criterion, tool-call-validity expert named as the fork's payload.
  Nothing built yet.
