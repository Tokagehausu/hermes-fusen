"""Fusen — the three tools Hermes gets.

They are one family, not five: list/get/search/read a note, pin/unpin it, write
it. The tool list is fixed at load, so turning rewriting on or off never changes
what the model sees mid-conversation (that would invalidate the prefix cache);
the switch only changes what ``fusen_write`` is allowed to do.

``auto_edit`` off means writes become proposals the user confirms. The model is
told so plainly in the result, so it does not claim a change it did not make.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from . import fusen_inject, fusen_store

logger = logging.getLogger(__name__)

_ctx: Any = None


def bind(ctx: Any) -> None:
    global _ctx
    _ctx = ctx


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _fail(message: str, **extra: Any) -> str:
    return _json({"ok": False, "error": message, **extra})


def _session(kwargs: dict[str, Any], args: dict[str, Any]) -> str:
    """The conversation a call acts on: explicit arg first, then the agent's."""
    explicit = args.get("session_id")
    if explicit:
        try:
            return fusen_store.session_key(explicit)
        except fusen_store.FusenError as exc:
            raise fusen_store.FusenError(str(exc)) from exc
    current = str(kwargs.get("session_id") or kwargs.get("task_id") or "")
    if not current:
        raise fusen_store.FusenError("no active conversation in this context")
    return fusen_store.session_key(current)


def _brief(note: dict[str, Any]) -> dict[str, Any]:
    body = note["body"].strip()
    return {
        "id": note["id"],
        "name": note["name"],
        "color": note["color"],
        "rev": note["rev"],
        "author": note["author"],
        "updated_at": note["updated_at"],
        "sessions": len(note["sessions"]),
        "excerpt": body[:160] + (" …" if len(body) > 160 else ""),
    }


# ── fusen_notes ─────────────────────────────────────────────────────────

SCHEMA_NOTES = {
    "name": "fusen_notes",
    "description": (
        "Sticky notes the user pinned to conversations. A note is a tag that carries an editable body: "
        "one note can be pinned to many conversations, and one conversation can carry several notes. "
        "Use this to read the notes on the current conversation (`action='list'`), inspect one "
        "(`'get'`), find the OTHER conversations sharing a note (`'search'` — then read them with "
        "`'read'`), or search note names and bodies by text. Notes are the user's own writing: treat "
        "them as context, and do not rewrite them with this tool (use fusen_write)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "search", "read"],
                "description": "list = notes on this conversation; get = one note in full; search = conversations sharing a note, or notes matching text; read = messages from a conversation.",
            },
            "scope": {
                "type": "string",
                "enum": ["session", "all"],
                "description": "For action='list': 'session' (default) = this conversation only; 'all' = every note.",
                "default": "session",
            },
            "note_id": {"type": "string", "description": "For get / search."},
            "query": {"type": "string", "description": "For search: text to match in note names and bodies."},
            "session_id": {"type": "string", "description": "For read: the conversation to read. Defaults to this one."},
            "limit": {"type": "integer", "description": "Max items to return (default 20).", "default": 20},
        },
        "required": ["action"],
    },
}


def fusen_notes(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        action = str(args.get("action") or "list")
        limit = max(1, min(100, int(args.get("limit") or 20)))
        state = fusen_store.load()

        if action == "list":
            if str(args.get("scope") or "session") == "all":
                notes = sorted(state["notes"].values(), key=lambda note: note["updated_at"], reverse=True)
                return _json({"ok": True, "notes": [_brief(note) for note in notes[:limit]], "total": len(notes)})
            sid = _session(kwargs, args)
            notes = fusen_store.notes_for(state, sid)
            return _json(
                {
                    "ok": True,
                    "session_id": sid,
                    "notes": [_brief(note) for note in notes],
                    "inject": state["settings"]["inject"],
                    "auto_edit": state["settings"]["auto_edit"],
                }
            )

        if action == "get":
            note = state["notes"].get(fusen_store.note_id(args.get("note_id")))
            if not note:
                return _fail("note not found")
            return _json(
                {
                    "ok": True,
                    "note": {
                        **_brief(note),
                        "body": note["body"],
                        "sessions": note["sessions"],
                        "history": [
                            {"rev": entry["rev"], "at": entry["at"], "author": entry["author"], "excerpt": entry["body"][:120]}
                            for entry in note["history"][-5:]
                        ],
                    },
                }
            )

        if action == "search":
            query = str(args.get("query") or "").strip().lower()
            wanted = str(args.get("note_id") or "").strip()

            if wanted:
                note = state["notes"].get(fusen_store.note_id(wanted))
                if not note:
                    return _fail("note not found")
                return _json(
                    {
                        "ok": True,
                        "note": _brief(note),
                        "session_ids": note["sessions"][:limit],
                        "count": len(note["sessions"]),
                        "hint": "call fusen_notes with action='read' and one of these session_ids for its messages",
                    }
                )

            if not query:
                return _fail("pass note_id or query")
            hits = [
                _brief(note)
                for note in state["notes"].values()
                if query in note["name"].lower() or query in note["body"].lower()
            ]
            return _json({"ok": True, "notes": hits[:limit], "count": len(hits)})

        if action == "read":
            sid = str(args.get("session_id") or "").strip()
            if not sid:
                sid = _session(kwargs, args)
            if _ctx is None or not hasattr(_ctx, "dispatch_tool"):
                return _fail("reading a conversation needs dispatch_tool, which this host does not expose")
            raw = _ctx.dispatch_tool("session_search", {"session_id": sid})
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                return _json({"ok": True, "session_id": sid, "raw": str(raw)[:8000]})
            return _json({"ok": True, "session_id": sid, "session": parsed})

        return _fail(f"unknown action: {action}")
    except fusen_store.FusenError as exc:
        return _fail(str(exc))
    except Exception as exc:  # never raise out of a tool
        logger.warning("fusen_notes failed", exc_info=True)
        return _fail(f"{type(exc).__name__}: {exc}")


# ── fusen_pin ─────────────────────────────────────────────────────

SCHEMA_PIN = {
    "name": "fusen_pin",
    "description": (
        "Pin an existing sticky note to a conversation, or unpin it. Pinning makes the note part of "
        "what this conversation is told from its next turn on; unpinning removes it. The note's body "
        "is shared by every conversation it is pinned to."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["attach", "detach"], "description": "attach = pin, detach = unpin."},
            "note_id": {"type": "string", "description": "Which note."},
            "session_id": {"type": "string", "description": "Target conversation. Defaults to this one."},
        },
        "required": ["action", "note_id"],
    },
}


def fusen_pin(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        action = str(args.get("action") or "")
        if action not in ("attach", "detach"):
            return _fail("action must be attach or detach")
        note_id = fusen_store.note_id(args.get("note_id"))
        sid = _session(kwargs, args)
        state, _ = fusen_store.mutate(
            lambda current: (fusen_store.attach(current, note_id, sid) if action == "attach" else fusen_store.detach(current, note_id, sid))
        )
        fusen_inject.mark_dirty(sid)
        note = state["notes"].get(note_id) or {}
        return _json(
            {
                "ok": True,
                "action": action,
                "note": _brief(note) if note else None,
                "session_id": sid,
                "pinned_here": len(fusen_store.notes_for(state, sid)),
            }
        )
    except fusen_store.FusenError as exc:
        return _fail(str(exc))
    except Exception as exc:
        logger.warning("fusen_pin failed", exc_info=True)
        return _fail(f"{type(exc).__name__}: {exc}")


# ── fusen_write ───────────────────────────────────────────────────

SCHEMA_WRITE = {
    "name": "fusen_write",
    "description": (
        "Rewrite a sticky note body, or revert it to an earlier revision. When the user has allowed "
        "automatic rewriting, the change is applied at once and every conversation carrying the note "
        "sees it. When they have not, this files a PROPOSAL instead: the result says so, and the user "
        "confirms it in the Fusen panel. Always pass expect_rev from what you last read, so a "
        "note the user edited by hand is not silently overwritten."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["write", "revert", "accept", "discard"], "description": "write = new body; revert = restore an earlier revision; accept/discard = settle a proposal."},
            "note_id": {"type": "string", "description": "Which note (write/revert)."},
            "body": {"type": "string", "description": "The new body (write). Keep it close to the original: notes are the user's own words."},
            "expect_rev": {"type": "integer", "description": "The rev you read. A mismatch aborts instead of overwriting."},
            "rev": {"type": "integer", "description": "For revert: which stored revision to restore. Omit for the previous one."},
            "pending_id": {"type": "string", "description": "For accept/discard."},
            "reason": {"type": "string", "description": "One line on why the body changed; shown to the user."},
        },
        "required": ["action"],
    },
}


def fusen_write(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        action = str(args.get("action") or "")
        sid = ""
        try:
            sid = _session(kwargs, args)
        except fusen_store.FusenError:
            sid = str(kwargs.get("session_id") or "")

        if action == "accept":
            pending_id = str(args.get("pending_id") or "")
            state, note = fusen_store.mutate(lambda current: fusen_store.accept(current, pending_id))
            fusen_inject.mark_dirty(sid)
            return _json({"ok": True, "applied": True, "note": _brief(note)})

        if action == "discard":
            pending_id = str(args.get("pending_id") or "")
            state, _ = fusen_store.mutate(lambda current: fusen_store.discard(current, pending_id))
            return _json({"ok": True, "applied": False, "discarded": pending_id})

        note_id = fusen_store.note_id(args.get("note_id"))

        if action == "revert":
            target = args.get("rev")
            state, note = fusen_store.mutate(lambda current: fusen_store.revert(current, note_id, target))
            fusen_inject.mark_dirty(sid)
            return _json({"ok": True, "applied": True, "note": _brief(note), "body": note["body"]})

        if action != "write":
            return _fail("action must be write, revert, accept or discard")

        body = str(args.get("body") or "")
        if not body.strip():
            return _fail("body cannot be empty; use revert or detach instead")

        state = fusen_store.load()
        note = state["notes"].get(note_id)
        if not note:
            return _fail("note not found")
        auto = bool(state["settings"]["auto_edit"])

        if auto:
            expect = args.get("expect_rev")
            state, note = fusen_store.mutate(
                lambda current: fusen_store.set_body(current, note_id, body, author="hermes", expect_rev=expect)
            )
            fusen_inject.mark_dirty(sid)
            return _json(
                {
                    "ok": True,
                    "applied": True,
                    "note": _brief(note),
                    "body": note["body"],
                    "pinned_sessions": len(note["sessions"]),
                }
            )

        reason = str(args.get("reason") or "")
        state, entry = fusen_store.mutate(lambda current: fusen_store.propose(current, note_id, body, reason=reason, sid=sid))
        return _json(
            {
                "ok": True,
                "applied": False,
                "proposed": True,
                "pending_id": entry["id"],
                "note": _brief(note),
                "message": "Automatic rewriting is off. The proposal is waiting for the user in the Fusen panel; do not describe the note as changed.",
            }
        )
    except fusen_store.FusenError as exc:
        return _fail(str(exc))
    except Exception as exc:
        logger.warning("fusen_write failed", exc_info=True)
        return _fail(f"{type(exc).__name__}: {exc}")
