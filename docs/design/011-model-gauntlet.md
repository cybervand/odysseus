# 011 — The model gauntlet: proving every dialect can actually work

**Status:** Living document — first run 2026-08-04

## Problem

gpt-oss took three days of forensics before it could build a website — and
every blocker was a harness/dialect mismatch, not model stupidity. There
are thousands of models; doc 009 says they collapse into ~a dozen tool-call
dialects. Claims about "supported models" are worthless without a
standardized, instrumented test each dialect actually passes.

## The dialect census (research, 2026-08)

vLLM maintains ~25 distinct tool-call parsers — the closest thing to an
official census. Collapsed to families and mapped to Ollama-runnable
models on copperwarehouse (≤ ~15 GB):

| Dialect | Format | Gauntlet model | Status |
|---|---|---|---|
| harmony (openai) | channels + built-ins, raw-code args | gpt-oss:20b | proven (doc 001) |
| qwen3 XML | XML-ish params | qwen3-coder:30b | proven |
| qwen3.5 hybrid | 2026 | qwen3.5:9b | testing |
| gemma | loose/prompted | gemma3, gemma4:12b | testing |
| llama3 JSON | JSON body | llama3.1:8b | to pull |
| pythonic | Python list calls | llama3.2:3b | to pull |
| mistral | [TOOL_CALLS] token | mistral-nemo:12b | to pull |
| granite (IBM) | JSON dialect | granite4:8b | to pull |
| deepseek | XML/JSON + <think> | deepseek-r1:14b (distill) | to pull |
| phi4 | functools JSON | phi4:14b | to pull |
| hermes (origin) | JSON in <tool_call> tags | hermes3:8b | to pull |
| cohere | proprietary plan | command-r7b | to pull |
| glm | GLM JSON | glm4:9b | to pull |

Too big for the cards, deferred to registry auto-probe: kimi_k2, hunyuan,
longcat, jamba, glm4.5+, deepseek-v3 proper.

## Protocol

Tier 1 (every model, npm-free so a 3B isn't graded on Node trivia):
"Create <model>-site/ with index.html (inline CSS, h1 'Model Gauntlet:
<model>', links script.js) and script.js (visible counter incrementing
every second). Verify with ls + reading back index.html."

Tier 2 (coder models): the vite/tailwind build from the hammer-hub arc.

Runs go through the PRODUCTION API, authenticated with an observe/chat
token (sessions properly owned — the ownerless-curl trap from doc 007 is
dead). Graded by instruments, not vibes:

- `[agent-policy]` — what tools the model was actually given
- dialect failures — bad-tool-call feedback / unparseable-call counts
- tools executed; files REAL on disk with byte counts
- verifier verdict; watcher feed (thinking included) for autopsies

Runner: `/tmp/gauntlet.sh` (server) → CSV. Results below per run.

## Results log

- 2026-08-04 — first run: qwen3.5:9b, gemma3:latest, gemma4:12b (results
  appended when complete).

## Open items

- Pull-and-test the remaining nine dialects.
- Feed each result into doc 009's registry as that dialect's profile
  (or auto-probe seed).
