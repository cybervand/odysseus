"""Dialect profiles — THE index of per-model-family tool-calling adaptations.

Doc 009 promised "profiles as data": one canonical internal state, per-family
adaptations declared in one place instead of constants scattered across
agent_loop and tool_parsing. Doc 012 holds the probe evidence behind every
row. If you are adding a per-model tool-calling behavior anywhere else,
stop — add a profile here and consume it there.

Field semantics:
- match: lowercase substrings tested against the model name. First matching
  profile wins — order PROFILES so more specific families come first.
- status: "fixed" (rematch-proven), "in-progress" (shipped, not yet proven),
  "diagnosed" (documented in doc 012, no runtime adaptation yet). Diagnosed
  rows MUST have no runtime knobs — they are index entries, not behavior.
- patterns: tool_parsing pattern IDs serving this family (documentation).
- turn_note: few-shot system note injected each round (doc 012 v2 lesson:
  show the EXACT parseable shapes, never describe abstractly — v1's abstract
  wording destabilized GLM's emission dialect itself and was rolled back).
  tests/test_dialect_profiles.py parses every note through our own chain.
- fenced_fallback: when a native-tools turn yields zero native calls and
  zero textual-markup blocks, re-parse once with ```bash fences enabled —
  for these families a bare fence IS the call (#3222 guard stays for
  everyone else).
"""
from dataclasses import dataclass
from typing import Optional, Tuple

_GLM_TURN_NOTE = (
    "To use a tool, write the call EXACTLY like these examples, "
    "then end your reply:\n\n"
    "bash\nmkdir -p myfolder\n\n"
    "or:\n\n"
    'write_file "myfolder/file.txt" "the complete file content here"\n\n'
    "One tool call per reply. After your reply ends, the system "
    "executes the call and sends you the REAL output — never "
    "write or predict a tool's output yourself. When the task is "
    "complete and verified, reply with a short summary and no "
    "tool call."
)

# DeepSeek-R1 distills were never trained on function calling and the Ollama
# registry template renders tool CALLS (DSML tokens) but never the tool
# DEFINITIONS — the model never sees the schemas, so it improvises a new
# serialization every run (ollama/ollama#8517, #10935). The community-proven
# anchor (MFDoom tool-calling template) is bare-JSON {name, parameters},
# which Pattern 3d parses in the PRIMARY pass — no fallback needed.
_DEEPSEEK_TURN_NOTE = (
    "To use a tool, reply with ONE JSON call EXACTLY like these examples, "
    "then end your reply:\n\n"
    '{"name": "bash", "parameters": {"command": "mkdir -p myfolder"}}\n\n'
    '{"name": "write_file", "parameters": {"path": "myfolder/file.txt", '
    '"content": "the complete file content here"}}\n\n'
    "One tool call per reply, as plain text after your thinking — no code "
    "fences, no shell commands named write_file. After your reply ends, the "
    "system executes the call and sends you the REAL output — never write "
    "or predict a tool's output yourself. When the task is complete and "
    "verified, reply with a short summary and no tool call."
)


@dataclass(frozen=True)
class DialectProfile:
    family: str
    match: Tuple[str, ...]
    status: str
    patterns: Tuple[str, ...] = ()
    turn_note: Optional[str] = None
    # "dialect": few-shot note anchoring EMISSION SHAPE — must contain the
    #   exact parseable bash/write_file examples (tested through our chain).
    # "behavioral": note steering conduct (channel discipline, turn-taking)
    #   for models whose emission is already clean — must contain NO tool
    #   shapes, so it cannot destabilize a working dialect (doc 012 v1
    #   lesson: abstract wording about shapes broke GLM's emission).
    note_kind: str = "dialect"
    fenced_fallback: bool = False
    notes: str = ""


PROFILES: Tuple[DialectProfile, ...] = (
    DialectProfile(
        family="harmony-builtins",
        match=("gpt-oss",),
        status="fixed",
        patterns=(),
        notes="browser/python builtin aliasing lives in tool_schemas (doc 001); "
              "gauntlet tier-1 and tier-2 PASS",
    ),
    DialectProfile(
        family="qwen-function-xml",
        match=("qwen",),
        status="fixed",
        patterns=("3c",),
        notes="<function=...> markup leaking into content; parsed regardless "
              "of skip_fenced",
    ),
    DialectProfile(
        family="deepseek-r1-fenced",
        match=("deepseek-r1",),
        status="in-progress",
        patterns=("1", "1-heredoc-split", "3d"),
        turn_note=_DEEPSEEK_TURN_NOTE,
        fenced_fallback=True,
        notes="never trained on function calling; registry template drops tool "
              "schemas; improvises per run — bare-JSON note anchors to 3d",
    ),
    DialectProfile(
        family="hermes-fenced",
        match=("hermes3", "hermes-3"),
        status="in-progress",
        patterns=("1",),
        fenced_fallback=True,
        notes="```bash fences with past-tense claims; fallback shipped, "
              "rematch pending",
    ),
    DialectProfile(
        family="glm-bare-invocation",
        match=("glm4", "glm-4"),
        status="fixed",
        patterns=("3e",),
        turn_note=_GLM_TURN_NOTE,
        notes="six serialization shapes parsed; campaign closed 2026-08-05 — "
              "9B compliance jitter remains, not a parser problem",
    ),
    DialectProfile(
        family="gemma4-content-mute",
        match=("gemma4",),
        status="in-progress",
        turn_note=(
            "Your visible reply is the ONLY channel that counts — your "
            "reasoning is invisible to the user and to the system. Never "
            "reply with just 'Done.' or a bare closer: state in the reply "
            "what you completed and what remains. If steps remain, do NOT "
            "end your reply — make the next tool call instead. Plans that "
            "exist only in your reasoning do not happen."
        ),
        note_kind="behavioral",
        notes="reasoning-rich, content-mute: replied 'Done.' while the "
              "reasoning channel ended mid-plan (2026-08-06 Vinterfjell run); "
              "native tools 3/3 clean, thinking via native field",
    ),
    DialectProfile(
        family="llama3-json",
        match=("llama3.1", "llama-3.1"),
        status="fixed",
        patterns=("3d",),
        notes='bare {"name","parameters"} in text; gauntlet zero-to-pass same day',
    ),
    DialectProfile(
        family="llama32-pythonic",
        match=("llama3.2",),
        status="diagnosed",
        notes="pythonic [func(args)] list emission — pattern queued (doc 012)",
    ),
    DialectProfile(
        family="planner-pathology",
        match=("mistral-nemo", "command-r"),
        status="diagnosed",
        notes="markdown plans instead of calls — needs plan-then-execute loop, "
              "not a parser (doc 012)",
    ),
    DialectProfile(
        family="phi4-silent-death",
        match=("phi4",),
        status="diagnosed",
        notes="empty responses when tools attached — Ollama-side trace needed "
              "before naming (doc 012)",
    ),
)


def profile_for(model: Optional[str]) -> Optional[DialectProfile]:
    m = (model or "").lower()
    if not m:
        return None
    for p in PROFILES:
        if any(k in m for k in p.match):
            return p
    return None


def turn_note_for(model: Optional[str]) -> Optional[str]:
    p = profile_for(model)
    return p.turn_note if p else None


def fenced_fallback_for(model: Optional[str]) -> bool:
    p = profile_for(model)
    return bool(p and p.fenced_fallback)
