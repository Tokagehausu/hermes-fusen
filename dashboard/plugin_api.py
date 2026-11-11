"""Fusen — the desktop's routes, mounted at ``/api/plugins/fusen/``.

The dashboard imports this file on its own (no package), so ``store`` is loaded
by path from the plugin root.

Everything the desktop can do is one batch of ops plus a state payload, so the
optimistic paint in ``desktop/plugin.js`` and a slash command in the CLI land on
the same code. The profile is not a parameter here: the host's
``/api/plugins/<name>/`` dependency reads ``?profile=`` off the request and binds
it into the home scope, so ``plugin_data_dir`` resolves to that profile's
``plugin-data`` for the whole handler. The desktop half sends the value; nothing
in this file needs to look at it.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException

router = APIRouter()


def _load_store():
    name = "hermes_fusen_store"
    if name not in sys.modules:
        path = Path(__file__).resolve().parent.parent / "fusen_store.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


store = _load_store()


def _announce(payload: dict[str, Any], sid: str = "") -> dict[str, Any]:
    """Tell every open window the state moved (event: plugin.fusen.notes.changed)."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(
            "fusen",
            "notes.changed",
            {"updated_at": payload.get("updated_at") or 0, "session_id": sid},
        )
    except BaseException as exc:  # the event bus is optional; the REST answer is not.
        # CancelledError is a BaseException, and a cancelled broadcast must not
        # turn a write that already succeeded into a 500.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        logging.getLogger(__name__).debug("fusen broadcast skipped: %s", exc)
    return payload


def _payload(body: dict[str, Any]) -> dict[str, Any]:
    sid = str(body.get("session_id") or "")
    if sid:
        try:
            sid = store.session_key(sid)
        except store.FusenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.payload(store.load(), sid=sid)


@router.get("/state")
def get_state(session_id: Optional[str] = None):
    """Every note, the settings, the pending proposals, and this conversation's pins."""
    return _payload({"session_id": session_id or ""})


@router.post("/ops")
def post_ops(body: dict = Body(...)):
    """Apply a batch of changes atomically. Returns the new state.

    ``session_id`` only shapes the payload (``session_note_ids``); it is not
    touched by the ops themselves.
    """
    ops = body.get("ops")
    sid = str(body.get("session_id") or "")
    try:
        state = store.apply_ops(ops, sid=store.session_key(sid) if sid else "")
    except store.FusenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _announce(state, sid)


@router.post("/arm")
def arm(body: dict = Body(...)):
    """Acknowledge a "new chat with this note" press (epoch ``since``).

    Nothing is written: the desktop opens the draft, then watches
    ``session.list`` for a conversation that started after ``since`` and claims it
    with a plain attach op. An abandoned press therefore costs nothing, and this
    file never touches the sessions table.
    """
    try:
        note_id = store.note_id(body.get("note_id"))
        since = float(body.get("since") or 0)
    except store.FusenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if since <= 0:
        raise HTTPException(status_code=400, detail="since is required")
    note = store.load()["notes"].get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="note not found")
    return {"ok": True, "note_id": note_id, "since": since, "name": note["name"]}
