"""The project ledger — doc 016: evidence-backed checkboxes as the
model's own memory.

Next-turn context carries only what the model SAID; what it DID vanishes
(a 13-round build remembered as "Done."). The ledger is a session-scoped
checklist of the project's requirements, updated after every effectful
agent run and injected at the start of the next agent turn.

Trust rules (the whole point — a wrong ledger is worse than none):
- The updater LLM proposes; the harness DISPOSES. An item may move to
  done/partial only when its evidence cites an anchor (path-like token or
  long fragment) that literally appears in the actions snapshot. No
  anchor -> the tick is rejected and the item stays open.
- Prior items never vanish: anything the updater drops is re-appended.
- Prior DONE items never silently un-tick (evidence was already banked);
  they may only move to failed, which needs its own anchor.
- A failing last effectful command gets a mechanical `!!` line whether or
  not the updater noticed.

Storage: latest-wins `ledger` events in the feed log (doc 014's second
consumer) — durable per-session, ephemeral for incognito, ignored by
every existing event consumer.
"""
import difflib
import json
import logging
import re
import time
from typing import Dict, List, Optional

from src.feed_log import get_log, emit

logger = logging.getLogger(__name__)

LEDGER_KIND = "ledger"

MAX_ITEMS = 20
MAX_SUBITEMS = 12
MAX_ITEM_TEXT = 120
MAX_EVIDENCE = 160
MAX_RENDER = 2600

_STATUS_RANK = {"open": 0, "partial": 1, "failed": 2, "done": 3}


# ── Data model helpers ──
# Canonical shape: {"version": 1, "updated_ts": float, "items": [
#   {"text", "status": open|partial|done|failed, "evidence",
#    "subitems": [{"text", "status": open|done, "evidence"}]}]}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()


def _same_item(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.75


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 2].rstrip() + " …"


# ── Parse (updater output -> ledger) ──

_TOP_RE = re.compile(r"^(\[[xX~ ]\]|!!)\s*(.*)$")
_SUB_RE = re.compile(r"^\s{2,}(\[[xX ]\])\s*(.*)$")


def _split_evidence(rest: str) -> tuple:
    if " | " in rest:
        text, ev = rest.split(" | ", 1)
    else:
        text, ev = rest, ""
    ev = re.sub(r"^(evidence|known)\s*:\s*", "", ev.strip(), flags=re.IGNORECASE)
    # strip a derived (k/n) counter — recomputed at render
    text = re.sub(r"\s*\(\d+/\d+\)\s*$", "", text.strip())
    return _clip(text, MAX_ITEM_TEXT), _clip(ev, MAX_EVIDENCE)


def parse_ledger_text(raw: str) -> Optional[dict]:
    """Strict-ish parse of the updater's checkbox lines. Returns None when
    nothing parseable came back (caller keeps the prior ledger)."""
    if not raw:
        return None
    text = raw.strip()
    # models love fences; shed them
    text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text.strip())
    items: List[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        msub = _SUB_RE.match(line)
        if msub and items and line.startswith((" ", "\t")):
            t, ev = _split_evidence(msub.group(2))
            if t:
                items[-1]["subitems"].append({
                    "text": t,
                    "status": "done" if msub.group(1).lower() == "[x]" else "open",
                    "evidence": ev,
                })
            continue
        mtop = _TOP_RE.match(line.strip())
        if not mtop:
            continue
        mark = mtop.group(1).lower()
        t, ev = _split_evidence(mtop.group(2))
        if not t:
            continue
        status = {"[x]": "done", "[~]": "partial", "[ ]": "open", "!!": "failed"}.get(mark, "open")
        items.append({"text": t, "status": status, "evidence": ev, "subitems": []})
    if not items:
        return None
    return {"version": 1, "updated_ts": time.time(), "items": items[: MAX_ITEMS * 2]}


# ── Render (ledger -> checkbox block) ──

_MARKS = {"open": "[ ]", "partial": "[~]", "done": "[x]", "failed": "!!"}


def render_ledger(ledger: dict, max_chars: int = MAX_RENDER) -> str:
    lines = []
    for it in (ledger or {}).get("items", []):
        subs = it.get("subitems") or []
        status = it.get("status", "open")
        counter = ""
        if subs:
            done_n = sum(1 for s in subs if s.get("status") == "done")
            counter = f" ({done_n}/{len(subs)})"
        ev = f" | {it['evidence']}" if it.get("evidence") else ""
        lines.append(f"{_MARKS.get(status, '[ ]')} {it['text']}{counter}{ev}")
        for s in subs:
            sev = f" | {s['evidence']}" if s.get("evidence") else ""
            lines.append(f"    {_MARKS.get(s.get('status', 'open'), '[ ]')} {s['text']}{sev}")
    out = "\n".join(lines)
    if len(out) > max_chars:
        # shed detail, never items: first drop evidence from done subitems,
        # then collapse fully-done parents to their counter line
        for it in (ledger or {}).get("items", []):
            for s in it.get("subitems") or []:
                if s.get("status") == "done":
                    s["evidence"] = ""
        lines = []
        for it in (ledger or {}).get("items", []):
            subs = it.get("subitems") or []
            done_n = sum(1 for s in subs if s.get("status") == "done")
            counter = f" ({done_n}/{len(subs)})" if subs else ""
            ev = f" | {it['evidence']}" if it.get("evidence") else ""
            lines.append(f"{_MARKS.get(it.get('status', 'open'), '[ ]')} {it['text']}{counter}{ev}")
            if subs and done_n < len(subs):
                for s in subs:
                    sev = f" | {s['evidence']}" if s.get("evidence") else ""
                    lines.append(f"    {_MARKS.get(s.get('status', 'open'), '[ ]')} {s['text']}{sev}")
        out = "\n".join(lines)
    return out[:max_chars]


# ── Evidence gate ──

def _has_anchor(evidence: str, snapshot: str) -> bool:
    """True when the evidence cites something that literally appears in the
    actions snapshot: a path-like token or any token of 8+ chars."""
    if not evidence or not snapshot:
        return False
    snap = snapshot.lower()
    for tok in re.split(r"[\s,;()\[\]]+", evidence.lower()):
        tok = tok.strip("\"'`.")
        if len(tok) < 4:
            continue
        if ("/" in tok or "." in tok or len(tok) >= 8) and tok in snap:
            return True
    return False


def _enforce(prior: Optional[dict], proposed: dict, snapshot: str,
             tool_events: Optional[List[dict]], effectful_tools=frozenset()) -> dict:
    """Apply the trust rules to the updater's proposal."""
    prior_items = (prior or {}).get("items", [])
    out_items: List[dict] = []
    matched_prior = set()

    for it in proposed.get("items", []):
        pmatch = None
        for idx, p in enumerate(prior_items):
            if idx not in matched_prior and _same_item(p["text"], it["text"]):
                pmatch = (idx, p)
                break
        if pmatch:
            matched_prior.add(pmatch[0])
            p = pmatch[1]
            # tick gate: new done/partial claims need an anchor
            newly_done = it["status"] in ("done", "partial") and \
                _STATUS_RANK[it["status"]] > _STATUS_RANK.get(p.get("status", "open"), 0)
            if newly_done and not (_has_anchor(it.get("evidence", ""), snapshot)
                                   or any(s.get("status") == "done" and _has_anchor(s.get("evidence", ""), snapshot)
                                          for s in it.get("subitems") or [])):
                it["status"] = p.get("status", "open")
                if it.get("evidence"):
                    it["evidence"] = _clip("unverified: " + it["evidence"], MAX_EVIDENCE)
                logger.info("[ledger] tick rejected (no anchor): %s", it["text"][:60])
            # done never silently un-ticks
            if p.get("status") == "done" and it["status"] in ("open", "partial"):
                it["status"] = "done"
                it["evidence"] = it.get("evidence") or p.get("evidence", "")
            if it["status"] == "failed" and p.get("status") == "done" and \
                    not _has_anchor(it.get("evidence", ""), snapshot):
                it["status"] = "done"
                it["evidence"] = p.get("evidence", "")
            # sub-tick gate + prior-sub merge
            prior_subs = {s["text"]: s for s in p.get("subitems") or []}
            for s in it.get("subitems") or []:
                ps = None
                for pt, cand in prior_subs.items():
                    if _same_item(pt, s["text"]):
                        ps = cand
                        break
                was_done = bool(ps and ps.get("status") == "done")
                if s.get("status") == "done" and not was_done and \
                        not _has_anchor(s.get("evidence", ""), snapshot):
                    s["status"] = "open"
                    if s.get("evidence"):
                        s["evidence"] = _clip("unverified: " + s["evidence"], MAX_EVIDENCE)
                if was_done:
                    s["status"] = "done"
                    s["evidence"] = s.get("evidence") or ps.get("evidence", "")
        else:
            # brand-new item: ticks still need anchors
            if it["status"] in ("done", "partial") and \
                    not _has_anchor(it.get("evidence", ""), snapshot) and \
                    not any(_has_anchor(s.get("evidence", ""), snapshot)
                            for s in it.get("subitems") or []):
                it["status"] = "open"
            for s in it.get("subitems") or []:
                if s.get("status") == "done" and not _has_anchor(s.get("evidence", ""), snapshot):
                    s["status"] = "open"
        it["subitems"] = (it.get("subitems") or [])[:MAX_SUBITEMS]
        out_items.append(it)

    # anything the updater dropped survives with its prior state
    for idx, p in enumerate(prior_items):
        if idx not in matched_prior:
            out_items.append(p)

    # parent status derives from subitem state: all done -> done, some -> partial,
    # none -> whatever it was (a parent can't stay "done" over open subs)
    for it in out_items:
        subs = it.get("subitems") or []
        if subs and it["status"] != "failed":
            done_n = sum(1 for s in subs if s.get("status") == "done")
            if done_n == len(subs):
                it["status"] = "done"
            elif done_n:
                it["status"] = "partial"
            elif it["status"] == "done":
                it["status"] = "partial"

    # mechanical failure line: last effectful command failed and no !! covers it
    last_eff = None
    for ev in tool_events or []:
        if ev.get("tool") in effectful_tools:
            last_eff = ev
    if last_eff is not None:
        try:
            rc = int(last_eff.get("exit_code", 0) or 0)
        except (TypeError, ValueError):
            rc = 0
        if rc != 0:
            head = _clip((last_eff.get("command") or last_eff.get("tool") or "command"), 80)
            if not any(it["status"] == "failed" and _same_item(it["text"], head)
                       for it in out_items):
                out_items.append({
                    "text": _clip(f"{head} exited {rc} - unaddressed", MAX_ITEM_TEXT),
                    "status": "failed", "evidence": "", "subitems": [],
                })

    return {"version": 1, "updated_ts": time.time(), "items": out_items[:MAX_ITEMS]}


# ── Storage ──

def load_ledger(session_id: str, incognito: bool = False, log=None) -> Optional[dict]:
    try:
        payload = (log or get_log(incognito)).latest(session_id, LEDGER_KIND)
        if not payload:
            return None
        data = json.loads(payload)
        return data if isinstance(data, dict) and data.get("items") else None
    except Exception as e:
        logger.warning("[ledger] load failed for %s: %s", session_id, e)
        return None


def save_ledger(session_id: str, ledger: dict, incognito: bool = False, log=None) -> None:
    try:
        payload = json.dumps(ledger)
        if log is not None:
            log.append(session_id, LEDGER_KIND, payload)
        else:
            emit(session_id, LEDGER_KIND, payload, incognito=incognito)
    except Exception as e:
        logger.warning("[ledger] save failed for %s: %s", session_id, e)


# ── Context injection ──

_HEADER = (
    "Project ledger - the evidence-based record of YOUR OWN prior work in "
    "this session, maintained by the system from tool calls that actually "
    "executed. Checked [x] items are DONE - do not repeat them; their noted "
    "paths, URLs and ports are real and usable. Unchecked [ ] items are NOT "
    "done. [~] means partially done - finish the unchecked sub-items, whose "
    "notes carry what is already known (a URL means found, not downloaded). "
    "Lines starting with !! are failures still unaddressed.\n\n"
)


def ledger_context_message(session_id: str, incognito: bool = False, log=None) -> Optional[Dict]:
    ledger = load_ledger(session_id, incognito=incognito, log=log)
    if not ledger:
        return None
    body = render_ledger(ledger)
    if not body.strip():
        return None
    return {"role": "system", "content": _HEADER + body}


# ── The updater ──

def _updater_prompt(prior_text: str, instruction: str, snapshot: str) -> str:
    return (
        "You maintain a project ledger: a checklist of the user's project "
        "requirements with evidence of what has ACTUALLY been done.\n\n"
        "Rules:\n"
        "- A box may be checked ONLY from the actions record below. Cite the "
        "exact command, file path, or output fragment after ' | '. "
        "No citation = the box stays open. The assistant CLAIMING something "
        "is done is not evidence.\n"
        "- Extract requirements from the request: each numbered step, each "
        "named file or path, each show/state/write instruction is one item. "
        "Never invent requirements.\n"
        "- When one requirement covers several similar things (N images, N "
        "pages), list each as an indented sub-item. An unchecked sub-item "
        "keeps any useful known fact (a URL, a path) after ' | '.\n"
        "- Keep every existing item. Keep checked items checked. Add new "
        "requirements from the latest request if they are not covered.\n"
        "- Record command failures as lines starting with !!.\n\n"
        "Format, exactly one item per line:\n"
        "[x] requirement | evidence: command/path/output fragment\n"
        "[~] parent requirement\n"
        "    [x] sub-item | evidence: ...\n"
        "    [ ] sub-item | known: URL or fact, or nothing\n"
        "[ ] requirement not yet done\n"
        "!! failure description | evidence: ...\n\n"
        f"Current ledger (empty means new project - extract requirements):\n"
        f"<ledger>\n{prior_text or '(empty)'}\n</ledger>\n\n"
        f"The user's request:\n<request>\n{_clip(instruction, 4000)}\n</request>\n\n"
        f"Actions the assistant took this turn:\n<actions>\n{snapshot[:8000]}\n</actions>\n\n"
        "Output ONLY the updated ledger lines, nothing else."
    )


async def update_ledger(
    session_id: str, instruction: str, tool_events: List[dict], snapshot: str,
    *, endpoint_url: str, model: str, headers: dict,
    incognito: bool = False, effectful_tools=frozenset(), log=None,
) -> Optional[dict]:
    """Run the updater LLM over (prior ledger, request, actions snapshot),
    enforce the trust rules, persist. Never raises; returns the new ledger
    or None when the update was skipped/kept."""
    from src.llm_core import llm_call_async
    from src.text_helpers import strip_thinking

    prior = load_ledger(session_id, incognito=incognito, log=log)
    prior_text = render_ledger(prior) if prior else ""
    prompt = _updater_prompt(prior_text, instruction, snapshot)
    raw = ""
    for attempt_tokens in (800, 1400):  # reasoning models can think past small budgets
        try:
            raw = await llm_call_async(
                url=endpoint_url, model=model,
                messages=[{"role": "user", "content": prompt}],
                headers=headers, temperature=0.0,
                max_tokens=attempt_tokens, timeout=60,
            )
        except Exception as e:
            logger.warning("[ledger] updater call failed: %s", e)
            return None
        raw = strip_thinking(raw or "")
        if raw.strip():
            break
    proposed = parse_ledger_text(raw)
    if proposed is None:
        logger.warning("[ledger] updater output unparseable (%d chars) — keeping prior ledger", len(raw or ""))
        return None
    final = _enforce(prior, proposed, snapshot, tool_events, effectful_tools=effectful_tools)
    save_ledger(session_id, final, incognito=incognito, log=log)
    n_done = sum(1 for i in final["items"] if i["status"] == "done")
    logger.info("[ledger] updated for %s: %d item(s), %d done", session_id, len(final["items"]), n_done)
    return final
