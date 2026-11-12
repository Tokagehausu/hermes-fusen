"""Fusen — slash commands.

The keyboard path, for when the desktop is not the surface. Same store, same
rules: the user typing here always counts as the user, so ``/fusenedit`` writes
even when automatic rewriting is off, and ``/fusenapply`` / ``/fusendismiss``
settle the proposals Hermes filed. The model's own tool can do neither.

Text comes from ``fusen_i18n``: English by default, Japanese when Hermes itself
is set to Japanese.
"""

from __future__ import annotations

import logging
from typing import Any

from . import fusen_inject, fusen_store
from .fusen_i18n import msg

logger = logging.getLogger(__name__)


def _item(note_or_entry_id: str, name: str) -> str:
    return msg("item", id=note_or_entry_id, name=name)


def _excerpt(text: str, limit: int = 60) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:limit] + (" …" if len(flat) > limit else "")


def _find(state: dict[str, Any], token: str) -> dict[str, Any]:
    """A note by id, else by exact name (case-insensitive), else by unique prefix."""
    token = token.strip()
    if not token:
        raise fusen_store.FusenError(msg("err.need_name"))
    note = state["notes"].get(token)
    if note:
        return note
    lowered = token.lower()
    by_name = [item for item in state["notes"].values() if item["name"].lower() == lowered]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise fusen_store.FusenError(msg("err.ambiguous", token=token))
    by_prefix = [item for item in state["notes"].values() if item["id"].startswith(token)]
    if len(by_prefix) == 1:
        return by_prefix[0]
    raise fusen_store.FusenError(msg("err.not_found", token=token))


def _sid(session_id: str) -> str:
    if not session_id:
        raise fusen_store.FusenError(msg("err.no_session"))
    return fusen_store.session_key(session_id)


def _pending_here(state: dict[str, Any], sid: str) -> list[dict[str, Any]]:
    """Proposals waiting on the notes this conversation carries."""
    ids = {note["id"] for note in fusen_store.notes_for(state, sid)}
    return [entry for entry in state.get("pending") or () if entry["note_id"] in ids]


def _note_name(state: dict[str, Any], note_id: str) -> str:
    note = state["notes"].get(note_id)
    return note["name"] if note else note_id


def _guard(name: str, fn, *args: Any, **kwargs: Any) -> str:
    """Run a command body; a store error becomes text, never a traceback."""
    try:
        return fn(*args, **kwargs)
    except fusen_store.FusenError as exc:
        return f"{exc}"
    except Exception as exc:
        logger.warning("%s command failed", name, exc_info=True)
        return msg("failed", error=f"{type(exc).__name__}: {exc}")


# ── /fusen ───────────────────────────────────────────────────────────────


def _fusen(raw_args: str, session_id: str) -> str:
    sid = _sid(session_id)
    token = (raw_args or "").strip()
    state = fusen_store.load()

    if not token:
        notes = fusen_store.notes_for(state, sid)
        if not notes:
            return f"{msg('none_here')}\n{msg('usage')}"
        mark = msg("mark_auto") if state["settings"]["auto_edit"] else msg("mark_propose")
        lines = [msg("list_header", count=len(notes))]
        for note in notes:
            lines.append(msg("list_row", id=note["id"], name=note["name"], rev=note["rev"], mark=mark))
            if note["body"]:
                lines.append(f"    {note['body'][:120]}")
        waiting = _pending_here(state, sid)
        if waiting:
            lines.append(msg("pending_header", count=len(waiting)))
            for entry in waiting:
                lines.append(
                    msg(
                        "pending_row",
                        id=entry["id"],
                        name=_note_name(state, entry["note_id"]),
                        excerpt=_excerpt(entry["body"]),
                    )
                )
            lines.append(msg("pending_hint"))
        return "\n".join(lines)

    # An existing note: pin it here.
    try:
        note = _find(state, token)
    except fusen_store.FusenError:
        note = None

    if note:
        state, _ = fusen_store.mutate(lambda current: fusen_store.attach(current, note["id"], sid))
        fusen_inject.mark_dirty(sid)
        here = len(fusen_store.notes_for(state, sid))
        return msg("pinned", name=note["name"], id=note["id"], count=here)

    state, created = fusen_store.mutate(lambda current: fusen_store.create(current, name=token, pin_to=sid))
    fusen_inject.mark_dirty(sid)
    return msg("created", name=created["name"], id=created["id"])


def fusen_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    return _guard("fusen", _fusen, raw_args, session_id)


# ── /unfusen ─────────────────────────────────────────────────────────────


def _unfusen(raw_args: str, session_id: str) -> str:
    sid = _sid(session_id)
    token = (raw_args or "").strip()
    state = fusen_store.load()
    notes = fusen_store.notes_for(state, sid)
    if not notes:
        return msg("none_here")

    if not token:
        if len(notes) != 1:
            listing = " / ".join(_item(note["id"], note["name"]) for note in notes)
            return msg("which_unpin", listing=listing)
        target = notes[0]
    else:
        target = _find(state, token)

    fusen_store.mutate(lambda current: fusen_store.detach(current, target["id"], sid))
    fusen_inject.mark_dirty(sid)
    return msg("unpinned", name=target["name"])


def unfusen_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    return _guard("unfusen", _unfusen, raw_args, session_id)


# ── /fusenedit ───────────────────────────────────────────────────────────


def _fusenedit(raw_args: str, session_id: str) -> str:
    sid = _sid(session_id)
    text = (raw_args or "").strip()
    if not text:
        return msg("edit_need_text")
    state = fusen_store.load()
    notes = fusen_store.notes_for(state, sid)
    if not notes:
        return msg("edit_no_notes")

    note = sorted(notes, key=lambda item: item["updated_at"], reverse=True)[0]
    if len(notes) > 1:
        explicit = None
        for candidate in notes:
            for prefix in (candidate["id"], candidate["name"]):
                if text.startswith(prefix + " "):
                    explicit = (candidate, text[len(prefix) + 1 :].strip())
                    break
            if explicit:
                break
        if not explicit:
            listing = " / ".join(_item(item["id"], item["name"]) for item in notes)
            return msg("edit_ambiguous", name=note["name"], listing=listing, id=note["id"], text=text[:40])
        note, text = explicit
        if not text:
            return msg("edit_empty")

    state, updated = fusen_store.mutate(lambda current: fusen_store.set_body(current, note["id"], text, author="user"))
    fusen_inject.mark_dirty(sid)
    return msg("edited", name=updated["name"], rev=updated["rev"], count=len(updated["sessions"]))


def fusenedit_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    return _guard("fusenedit", _fusenedit, raw_args, session_id)


# ── /fusenundo ───────────────────────────────────────────────────────────


def _fusenundo(raw_args: str, session_id: str) -> str:
    sid = _sid(session_id)
    state = fusen_store.load()
    notes = fusen_store.notes_for(state, sid)
    if not notes:
        return msg("edit_no_notes")
    token = (raw_args or "").strip()
    target = _find(state, token) if token else sorted(notes, key=lambda item: item["updated_at"], reverse=True)[0]
    state, note = fusen_store.mutate(lambda current: fusen_store.revert(current, target["id"]))
    fusen_inject.mark_dirty(sid)
    return msg("undone", name=note["name"], rev=note["rev"])


def fusenundo_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    return _guard("fusenundo", _fusenundo, raw_args, session_id)


# ── /fusenapply, /fusendismiss — the user settles Hermes' proposals ─────


def _settle(raw_args: str, session_id: str, *, apply: bool) -> str:
    sid = _sid(session_id)
    token = (raw_args or "").strip()
    state = fusen_store.load()

    if token:
        entry = next((item for item in state.get("pending") or () if item["id"] == token), None)
        if entry is None:
            raise fusen_store.FusenError(msg("err.proposal_not_found", token=token))
    else:
        waiting = _pending_here(state, sid)
        if not waiting:
            return msg("no_proposals")
        if len(waiting) > 1:
            listing = " / ".join(_item(item["id"], _note_name(state, item["note_id"])) for item in waiting)
            return msg("which_proposal", listing=listing)
        entry = waiting[0]

    name = _note_name(state, entry["note_id"])
    if not apply:
        fusen_store.mutate(lambda current: fusen_store.discard(current, entry["id"]))
        return msg("dismissed", name=name)

    state, note = fusen_store.mutate(lambda current: fusen_store.accept(current, entry["id"]))
    fusen_inject.mark_dirty(sid)
    return msg("applied", name=note["name"], rev=note["rev"])


def fusenapply_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    return _guard("fusenapply", _settle, raw_args, session_id, apply=True)


def fusendismiss_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    return _guard("fusendismiss", _settle, raw_args, session_id, apply=False)
