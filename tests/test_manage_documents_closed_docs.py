"""manage_documents must see the LIBRARY, not the editor's open tabs.

`is_active` only tracks "open in a session" — a UI presence flag. list and
read filtered on it, so the moment the user closed a document's tab, the
document ceased to exist for the agent: the library manifest advertised
fire_cube.frag, `manage_documents read` with the exact id returned
"Document not found", and the model reported it couldn't find its own file.
Archived is the real soft-delete and stays hidden.
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


def _seed(title, *, is_active, archived=False, owner="admin"):
    doc_id = str(uuid.uuid4())
    db = _TS()
    try:
        db.add(Document(
            id=doc_id, title=title, language="markdown",
            current_content=f"content of {title}", version_count=1,
            is_active=is_active, archived=archived, owner=owner,
        ))
        db.commit()
    finally:
        db.close()
    return doc_id


@pytest.fixture(autouse=True)
def _bind_db(monkeypatch):
    monkeypatch.setattr(cdb, "SessionLocal", _TS)


async def _manage(args_json):
    from src.agent_tools.document_tools import ManageDocumentTool
    return await ManageDocumentTool().execute(args_json, {"owner": "admin"})


@pytest.mark.asyncio
async def test_read_works_on_closed_document():
    doc_id = _seed("fire_cube.frag", is_active=False)
    res = await _manage(f'{{"action": "read", "document_id": "{doc_id}"}}')
    assert res.get("exit_code", 0) == 0, res
    assert "content of fire_cube.frag" in str(res.get("response", ""))


@pytest.mark.asyncio
async def test_list_includes_closed_marks_open():
    closed = _seed("closed-doc", is_active=False)
    opened = _seed("open-doc", is_active=True)
    res = await _manage('{"action": "list"}')
    text = str(res.get("response", ""))
    ids = [d["id"] for d in res.get("documents", [])]
    assert closed in ids and opened in ids
    assert "open in editor" in text


@pytest.mark.asyncio
async def test_archived_stays_hidden():
    archived = _seed("archived-doc", is_active=True, archived=True)
    res = await _manage('{"action": "list"}')
    assert archived not in [d["id"] for d in res.get("documents", [])]
