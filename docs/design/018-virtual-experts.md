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

- 2026-08-08 — Doc created from the user's v0.1 draft + investigation:
  single-box revision (no CPU fallback, contention protocol, pruned-fits-
  one-card endgame), transcript + source verdict (O2 answered: reference
  is answer substitution — we invent, not port), strategy ladder with
  kill criterion, tool-call-validity expert named as the fork's payload.
  Nothing built yet.
