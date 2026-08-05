"""Preview route (/preview/*, design doc 010 tier 1).

Serves agent-built files strictly under DATA_DIR. Confinement is the whole
point: traversal, dotfiles, and the app database must 404; directories
redirect to trailing slash then serve index.html so relative asset links
resolve; unauthenticated callers on a configured-auth deployment get 401.

Transport note: httpx.ASGITransport on the test's own event loop (see
test_notes_fail_closed_auth.py for why TestClient deadlocks).
"""
import os

import httpx
import pytest
from fastapi import FastAPI

import src.constants as consts
import routes.preview_routes as pr


def _app(user="admin"):
    app = FastAPI()
    app.include_router(pr.router)

    @app.middleware("http")
    async def _identity(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    return app


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    site = tmp_path / "coffee_site"
    site.mkdir()
    (site / "index.html").write_text("<h1>Copper Warehouse</h1>", encoding="utf-8")
    (site / "styles.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "app.db").write_text("sqlite", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    monkeypatch.setattr(consts, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pr, "DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.anyio
async def test_serves_file_with_mime(workspace):
    async with _client(_app()) as c:
        r = await c.get("/preview/coffee_site/index.html")
    assert r.status_code == 200
    assert "Copper Warehouse" in r.text
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.anyio
async def test_dir_redirects_then_serves_index(workspace):
    async with _client(_app()) as c:
        r = await c.get("/preview/coffee_site", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"] == "/preview/coffee_site/"
        r2 = await c.get("/preview/coffee_site/")
    assert r2.status_code == 200
    assert "Copper Warehouse" in r2.text


@pytest.mark.anyio
async def test_traversal_and_secrets_404(workspace):
    async with _client(_app()) as c:
        for path in (
            "/preview/../../etc/passwd",
            "/preview/..%2f..%2fetc%2fpasswd",
            "/preview/app.db",
            "/preview/.env",
            "/preview/coffee_site/../.env",
        ):
            r = await c.get(path)
            assert r.status_code == 404, path


@pytest.mark.anyio
async def test_html_gets_back_overlay_but_assets_do_not(workspace):
    async with _client(_app()) as c:
        html = await c.get("/preview/coffee_site/index.html")
        css = await c.get("/preview/coffee_site/styles.css")
    assert "Back to Odysseus" in html.text
    assert html.text.rstrip().endswith("</body>") or "&#8592; Odysseus</a>" in html.text
    assert "Odysseus" not in css.text
    # Display-only chrome — the file on disk is untouched.
    on_disk = (workspace / "coffee_site" / "index.html").read_text(encoding="utf-8")
    assert "Odysseus" not in on_disk


@pytest.mark.anyio
async def test_missing_file_404(workspace):
    async with _client(_app()) as c:
        r = await c.get("/preview/coffee_site/nope.js")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_unauthenticated_401_when_auth_configured(workspace, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("LOCALHOST_BYPASS", "false")
    app = _app(user=None)
    app.state.auth_manager = SimpleNamespace(is_configured=True)
    # Non-loopback peer so the loopback fall-throughs stay out of the way.
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 51000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/preview/coffee_site/index.html")
    assert r.status_code == 401
