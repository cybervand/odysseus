# 003 — Document library awareness

**Status:** Shipped (6620ffd5, f8b29410)

## Problem

An agent that creates a document can truthfully deny being able to access it
one turn later. Four stacked gates, each individually defensible:
history trimming drops the authoring turn (token budget, agent_loop
~`compute_input_token_budget`); the open document is only injected into
context on doc-edit phrasing (`_turn_targets_active_document` — small models
otherwise overfit to whatever is open); `manage_documents` is keyword-gated
behind admin vocabulary (`_ADMIN_KEYWORDS`); and nothing ever told the model
a library exists. Observed live: gpt-oss wrote a GLSL shader document, then
in the SAME open session claimed no knowledge of it; later, in a NEW chat,
it asked the user for a *file path* to that shader while Odysseus's memory
system fed it the document's name.

A hidden coupling made this worse: the UI's phantom open-document carryover
(see doc 007 cache/session notes) had been accidentally rebinding documents
into new sessions — new chats *seemed* document-aware until that bug was
fixed, which re-blinded them.

## Decision

Mirror the uploaded-files pattern (`_uploaded_files_context_message`):

- `_session_documents(session_id)` + `_owner_library_documents(owner,
  exclude_session, limit=5)` — titles/ids/language/date only, never content.
- `_session_library_context_message(...)` injects a two-section manifest
  each agent turn: this session's documents, plus the owner's most recent
  from other chats ("also yours to read/edit"). Ends with: read via
  `manage_documents action="read"`; documents need **no file path**; do not
  claim they are lost.
- `manage_documents` + `edit_document` are force-offered whenever either
  list is non-empty — no keyword roulette for reaching your own artifacts.

Cost: a few dozen tokens per turn, only in sessions where documents exist.

## Rejected alternatives

- **Inject document content** — token cost unbounded; the gates exist
  precisely because content injection makes small models overfit.
- **Add phrases to the keyword lists** — fragile whack-a-mole; "the shader
  you wrote" matches nothing and never will exhaustively.
- **Always offer all document tools** — upstream keeps the always-set tiny
  deliberately for weak models; scoped force-offer preserves that.
- **Rely on Odysseus's memory system** — it recalls names, not access; a
  name without a reachable tool produces "give me the file path."

## Validation

`tests/test_session_library_awareness.py`. Live: model's first move on "what
was that shader you wrote?" went from denial → `manage_documents
{"action": "list"}`.

## Open items

- Title-based references still degrade when models create duplicate titles
  (see doc 004's gotcha).
- Library section is capped at 5; a power user with many active projects may
  need recency+relevance selection instead.

## Decision log

- 2026-08-03 — session manifest + force-offer (6620ffd5).
- 2026-08-04 — owner-library section for new chats; "no file path" line (f8b29410).
- 2026-08-04 — manage_documents list/read no longer filter on `is_active`
  (978c792c). `is_active` = "open in the editor panel", a UI presence flag;
  filtering on it made a closed document "not found" by exact id while this
  manifest advertised it. list = all non-archived owned docs, open ones
  marked; read works on closed docs; archived remains the soft-delete.
