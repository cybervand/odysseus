"""The agent must know about, and be able to reach, its own documents.

Live failure this guards against: gpt-oss wrote a GLSL shader into a
session document, and one turn later — same session, page never closed —
denied any knowledge of it and claimed it had no access. Four stacked
gates caused that: history trimming dropped the authoring turn, the open
document is only injected on doc-edit phrasing, manage_documents is
keyword-gated, and nothing ever told the model the library existed.

The fix: a titles-only library manifest injected every agent turn the
session has documents, plus manage_documents/edit_document force-offered
alongside it.
"""
import src.agent_loop as agent_loop


def _docs():
    return [
        {"id": "d1", "title": "Cube Shader Pair", "language": "markdown",
         "updated_at": "2026-08-02 17:37:31.926855"},
        {"id": "d2", "title": "Code (glsl)", "language": "markdown",
         "updated_at": "2026-08-02 17:36:00.000000"},
    ]


def test_manifest_lists_titles_ids_and_howto():
    msg = agent_loop._session_library_context_message(_docs())
    assert msg is not None
    text = str(msg.get("content"))
    assert "Cube Shader Pair" in text
    assert "id=d1" in text and "id=d2" in text
    assert "manage_documents" in text
    # The whole point: forbid the "it's lost/inaccessible" answer.
    assert "inaccessible" in text


def test_manifest_carries_no_document_content():
    docs = _docs()
    msg = agent_loop._session_library_context_message(docs)
    # Titles yes, content no — the note must stay cheap.
    assert "ambientStrength" not in str(msg.get("content"))


def test_no_documents_no_manifest():
    assert agent_loop._session_library_context_message([]) is None


def test_session_documents_queries_by_session(monkeypatch):
    captured = {}

    class _Q:
        def __init__(self, rows): self._rows = rows
        def filter(self, *a): captured["filtered"] = True; return self
        def order_by(self, *a): return self
        def limit(self, n): captured["limit"] = n; return self
        def all(self): return self._rows

    class _DB:
        def query(self, *a):
            return _Q([("d1", "Cube Shader Pair", "markdown", "2026-08-02")])
        def close(self): captured["closed"] = True

    import core.database as core_db
    monkeypatch.setattr(core_db, "SessionLocal", lambda: _DB())
    docs = agent_loop._session_documents("sess-1")
    assert docs == [{"id": "d1", "title": "Cube Shader Pair",
                     "language": "markdown", "updated_at": "2026-08-02"}]
    assert captured.get("filtered") and captured.get("closed")
    assert captured.get("limit") == 8
