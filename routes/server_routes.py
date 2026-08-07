"""Named-server service routes (doc 017 §4).

The registry graduates from a model-side tool to a user-visible service:
the panel / server chip / /server slash commands all consume these. Same
owner-scoped authority as the manage_server tool — three doors, one core.
Deliberately model-free: in the messed-up-chat scenario the user can still
stop, restart, or re-attach a server even though the chat's model is
unusable.
"""
import logging

from fastapi import APIRouter, Form, HTTPException, Request

from core.database import Session as DbSession, SessionLocal
from src.auth_helpers import effective_user

logger = logging.getLogger(__name__)


def _visible(entry_owner, user) -> bool:
    """Owner-less legacy entries are everyone's; other users' servers are
    invisible (matches the manage_server tool's `_mine`)."""
    return entry_owner in (None, user)


def _chat_names(session_ids) -> dict:
    ids = [s for s in session_ids if s]
    if not ids:
        return {}
    db = SessionLocal()
    try:
        rows = db.query(DbSession.id, DbSession.name).filter(DbSession.id.in_(ids)).all()
        return {r[0]: r[1] for r in rows}
    finally:
        db.close()


def setup_server_routes():
    from src import bg_jobs

    router = APIRouter(prefix="/api", tags=["servers"])

    def _get_mine(request: Request, name: str) -> dict:
        st = bg_jobs.server_status(name)
        if st is None or not _visible(st.get("owner"), effective_user(request)):
            raise HTTPException(404, f"Server '{name}' not found")
        return st

    def _url(request: Request, port) -> str:
        host = request.url.hostname or "localhost"
        return f"http://{host}:{port}" if port else ""

    def _row(request: Request, st: dict, names: dict) -> dict:
        sid = st.get("session_id") or ""
        system = sid in (bg_jobs.SYSTEM_OWNER, bg_jobs.LEGACY_OPS_SESSION)
        return {
            "name": st["name"],
            "port": st.get("port"),
            "url": _url(request, st.get("port")),
            "running": bool(st.get("running")),
            "port_listening": bool(st.get("port_listening")),
            "uptime_s": st.get("uptime_s"),
            "autostart": bool(st.get("autostart")),
            "stopped": bool(st.get("stopped")),
            "cwd": st.get("cwd"),
            "command": st.get("command"),
            "chat_id": None if system else (sid or None),
            "chat_name": "system" if system else names.get(sid),
        }

    @router.get("/servers")
    def list_servers(request: Request):
        user = effective_user(request)
        mine = [s for s in bg_jobs.server_list() if _visible(s.get("owner"), user)]
        names = _chat_names([s.get("session_id") for s in mine])
        lo, hi = bg_jobs.port_range()
        return {"servers": [_row(request, s, names) for s in mine],
                "port_range": [lo, hi]}

    @router.post("/servers/{name}/stop")
    def stop_server(request: Request, name: str):
        _get_mine(request, name)
        st = bg_jobs.server_stop(name)
        return _row(request, st, _chat_names([st.get("session_id")]))

    @router.post("/servers/{name}/start")
    @router.post("/servers/{name}/restart")
    def restart_server(request: Request, name: str):
        # start-by-name on an existing entry IS a restart: relaunch the stored
        # command (the /server start hint on the stopped chip lands here).
        _get_mine(request, name)
        try:
            st = bg_jobs.server_restart(name)
        except bg_jobs.PortAllocationError as e:
            raise HTTPException(409, str(e))
        return _row(request, st, _chat_names([st.get("session_id")]))

    @router.post("/servers/{name}/remove")
    def remove_server(request: Request, name: str):
        _get_mine(request, name)
        bg_jobs.server_remove(name)
        return {"removed": name}

    @router.post("/servers/{name}/assign")
    def assign_server(request: Request, name: str, session_id: str = Form(...)):
        _get_mine(request, name)
        user = effective_user(request)
        db = SessionLocal()
        try:
            target = db.query(DbSession).filter(DbSession.id == session_id).first()
        finally:
            db.close()
        if target is None:
            # New chats persist on their FIRST message — adopting from a
            # fresh empty chat is the primary escape flow (doc 017: abandon
            # a poisoned chat, take the server along), so a missing row
            # means "not saved yet", not "bad id". Attachment is
            # presentation-only (capability follows owner), so a dangling
            # id is harmless if the chat never materializes.
            logger.info("[servers] assign %s -> not-yet-persisted chat %s", name, session_id)
        else:
            towner = target.owner
            if user is not None and towner is not None and towner != user:
                raise HTTPException(403, "Target chat belongs to another user")
        st = bg_jobs.server_assign(name, session_id)
        return _row(request, st, _chat_names([session_id]))

    @router.get("/servers/{name}/logs")
    def server_logs(request: Request, name: str):
        _get_mine(request, name)
        return {"name": name, "logs": bg_jobs.server_logs(name) or ""}

    return router
