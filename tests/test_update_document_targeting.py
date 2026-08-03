"""update_document must aim like edit_document, and never accept skeletons.

Live failure: asked to add a cloud background to fire_cube.frag, the model
called update_document — which had NO targeting — so the rewrite landed on
whatever document was 'active' (a different shader), AND the new content
was a template ("vec3 result = computeFire(); // placeholder function",
"(omitted for brevity)") that replaced the real shader wholesale. The
verifier saw a successful update with a diff and passed it.
"""
import tempfile
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb
from core.database import Document

_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_ENGINE = create_engine(
    f"sqlite:///{_TMPDB.name}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
cdb.Base.metadata.create_all(_ENGINE)
_TS = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False)

REAL_SHADER = "\n".join(f"line {i} of real shader code" for i in range(30))


def _seed(title, content=REAL_SHADER):
    doc_id = str(uuid.uuid4())
    db = _TS()
    try:
        db.add(Document(
            id=doc_id, title=title, language="markdown",
            current_content=content, version_count=1,
            is_active=True, owner="admin",
        ))
        db.commit()
    finally:
        db.close()
    return doc_id


def _content(doc_id):
    db = _TS()
    try:
        return db.query(Document).filter(Document.id == doc_id).first().current_content
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _bind_db(monkeypatch):
    monkeypatch.setattr(cdb, "SessionLocal", _TS)
    import src.database as sdb
    monkeypatch.setattr(sdb, "SessionLocal", _TS, raising=False)
    import src.agent_tools.document_tools as dt
    dt.set_active_document(None)


async def _update(content):
    from src.agent_tools.document_tools import UpdateDocumentTool
    return await UpdateDocumentTool().execute(content, {"owner": "admin"})


@pytest.mark.asyncio
async def test_doc_header_targets_named_document():
    right = _seed("fire_cube.frag")
    wrong = _seed("Code (glsl)")  # newer -> would win the fallback
    import src.agent_tools.document_tools as dt
    dt.set_active_document(wrong)
    res = await _update(f"DOC: {right}\nentirely new shader body\nwith two lines")
    assert res.get("doc_id") == right, res
    assert "entirely new shader" in _content(right)
    assert _content(wrong) == REAL_SHADER  # untouched


@pytest.mark.asyncio
async def test_elision_skeleton_is_refused():
    doc = _seed("real.frag")
    res = await _update(
        f"DOC: {doc}\nvoid main() {{\n  // existing fire calculations ... (omitted for brevity)\n}}"
    )
    assert res.get("exit_code") == 1
    assert "elided" in res.get("error", "") or "elision" in res.get("error", "").lower() or "Refused" in res.get("error", "")
    assert _content(doc) == REAL_SHADER  # nothing destroyed


@pytest.mark.asyncio
async def test_full_rewrite_longer_than_original_is_allowed():
    doc = _seed("short.md", content="tiny")
    res = await _update(f"DOC: {doc}\na genuinely complete replacement that is longer than the original")
    assert res.get("exit_code", 0) != 1
    assert "complete replacement" in _content(doc)


@pytest.mark.asyncio
async def test_unknown_target_errors_cleanly():
    _seed("whatever")
    res = await _update("DOC: no-such-doc-id\nnew content")
    assert "No document found" in res.get("error", "")
