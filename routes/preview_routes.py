"""Static preview of agent-built files — /preview/* (design doc 010, tier 1).

The agent builds real sites and scripts into the data dir; before this
route they dead-ended on the filesystem. Serves files strictly under
DATA_DIR so a built webpage is viewable the moment it exists. No
directory listings; dotfiles, dot-directories and the app database are
never served.
"""
import mimetypes
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from src.auth_helpers import require_user
from src.constants import DATA_DIR

router = APIRouter()

_DENY_BASENAMES = {"app.db", "app.db-wal", "app.db-shm"}

# Viewer chrome injected into served HTML only (never written to disk):
# without it a preview tab is a dead end — no way back to the chat.
_BACK_OVERLAY = (
    b'<a href="/" style="position:fixed;bottom:16px;right:16px;'
    b'z-index:2147483647;background:#1c1c1e;color:#fff;padding:8px 14px;'
    b'border-radius:999px;font:600 13px system-ui,sans-serif;'
    b'text-decoration:none;opacity:.85;box-shadow:0 2px 10px rgba(0,0,0,.35)"'
    b' title="Back to Odysseus">&#8592; Odysseus</a>'
)


def _resolve_preview_path(rel: str) -> str:
    """Resolve a preview path, confined to DATA_DIR (realpath defeats
    ../ traversal and symlink escapes)."""
    root = os.path.realpath(DATA_DIR)
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(status_code=404, detail="Not found")
    return target


def _denied(target: str) -> bool:
    root = os.path.realpath(DATA_DIR)
    rel = os.path.relpath(target, root)
    if rel == ".":
        return True
    for part in rel.split(os.sep):
        if part.startswith("."):
            return True
    return os.path.basename(target) in _DENY_BASENAMES


@router.get("/preview/{rel_path:path}")
async def preview_file(rel_path: str, request: Request):
    require_user(request)  # 401 when auth is configured; anonymous modes pass
    target = _resolve_preview_path(rel_path)
    if os.path.isdir(target):
        # Redirect dir hits to a trailing slash so the browser resolves the
        # page's relative asset links (styles.css, app.js) inside the dir.
        if rel_path and not rel_path.endswith("/"):
            return RedirectResponse(url=f"/preview/{rel_path}/")
        target = os.path.join(target, "index.html")
    if _denied(target) or not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Not found")
    media_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
    if media_type == "text/html":
        try:
            with open(target, "rb") as f:
                raw = f.read()
        except OSError:
            raise HTTPException(status_code=404, detail="Not found")
        idx = raw.lower().rfind(b"</body>")
        if idx != -1:
            raw = raw[:idx] + _BACK_OVERLAY + raw[idx:]
        else:
            raw = raw + _BACK_OVERLAY
        return Response(content=raw, media_type="text/html")
    return FileResponse(target, media_type=media_type)
