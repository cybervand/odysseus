# 004 — edit_document targeting and edit UX redesign

**Status:** Partially shipped (6f08338c); approved open items below

## Problem

`edit_document` had **no target argument**. The edit went to a
process-global active-document pointer, else the owner's most recently
updated document in ANY session. A model that read document A via
`manage_documents` silently edited document B and got "none of the FIND
blocks matched" — observed live with qwen3-coder immediately after doc 003
invited cross-document reads. Also observed: models typo UUIDs when
transcribing them (`2d3c` vs `2d7c` in one live run).

The exact-match FIND/REPLACE core is NOT the problem: refusal is the safe
failure mode (fuzzy matching corrupts documents silently), and it is the
shape every serious agent harness converged on. The support system around it
was missing.

## Decision (shipped)

- **Model-named target:** optional `DOC: <id-or-title>` first line in the
  edit-block text; `document_id` argument in the native JSON schema. Both
  protocols (tool_schemas.py native, tool_parsing.py fenced) converge on the
  same header; `extract_edit_target` parses it. A named target beats the
  active-doc pointer. Resolution: exact id, else newest title match
  (owner-scoped, `ilike`).
- **Retarget-on-miss:** if nothing matched and no target was named, scan the
  owner's 20 most recent documents; if EXACTLY one matches the edits, apply
  there with an explanatory `note` in the result. Ambiguity refuses.
- **Actionable error:** the no-match error names the document actually
  targeted and teaches the `DOC:` header.

Gotcha (accepted): title resolution picks the NEWEST document with that
title — a model that creates a duplicate then edits "by title" edits its
duplicate. Ids are the reliable path; tool descriptions steer to ids.

## Rejected alternatives

- **Fuzzy matching of FIND text** — silent corruption; hard no.
- **Line-number-based edits** — empirically worse for small models
  (off-by-ones, stale numbers after every successful edit).
- **Auto-retarget on ambiguity** (pick best match) — guessing where an edit
  lands is how documents get destroyed.

## Open items (approved 2026-08-04, not yet built)

1. **Show, don't just refuse:** FIND-miss error includes the
   nearest-matching region of the actual document so the model corrects in
   one round instead of flailing blind.
2. **Read-before-edit:** refuse edits to a document that wasn't read or
   written this turn, attaching the current content — kills the
   compose-FIND-from-stale-memory failure at the root.
3. **Size-aware routing:** for small documents (sub-~2KB), tools and errors
   should say plainly that `update_document` (full rewrite) is fine — one
   honest rewrite beats three failed surgical edits; models regenerate small
   documents reliably.

## Validation

`tests/test_edit_document_targeting.py`. Deterministic lab: `DOC: <id>`
edited exactly that document; ambiguous miss refused naming the target;
unique-text miss retargeted with note.

## Decision log

- 2026-08-04 — targeting + retarget + error shipped (6f08338c).
- 2026-08-04 — update_document gained the same `DOC:`/`document_id`
  targeting (it had none: a full rewrite aimed at fire_cube.frag landed on
  a different shader) plus an anti-clobber guard: a replacement containing
  elision markers ("omitted for brevity", "// placeholder", ...) that also
  shrinks the document is refused — a skeleton rewrite destroyed a real
  shader once (restored via the version-history endpoint). suggest_document
  still untargeted — lower risk (it never writes), do with open item 2
  (e0c365d2).
- 2026-08-04 — tool cards state the ground-truth target (1322d44e).
  Principle (user's, and correct): WHICH document a tool touched is harness
  truth from the tool result, never model narration. Card header shows an
  always-visible "→ <title>"; update_document's header previously showed the
  model's own first content line while the rewrite hit a different document.
