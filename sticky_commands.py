"""Sticky Tags — slash commands.

The keyboard path, for when the desktop is not the surface. Same store, same
rules: the user typing here always counts as the user, so ``/stickyedit`` writes
even when automatic rewriting is off.
"""

from __future__ import annotations

import logging
from typing import Any

from . import sticky_inject, sticky_store

logger = logging.getLogger(__name__)

USAGE = (
    "付箋: /sticky で一覧、/sticky <名前> でこの会話に貼る、"
    "/unsticky <名前|id> で外す、/stickyedit <本文> で書き換え、/stickyundo でひとつ戻す"
)


def _find(state: dict[str, Any], token: str) -> dict[str, Any]:
    """A note by id, else by exact name (case-insensitive), else by unique prefix."""
    token = token.strip()
    if not token:
        raise sticky_store.StickyError("付箋の名前かidを指定してください")
    note = state["notes"].get(token)
    if note:
        return note
    lowered = token.lower()
    by_name = [item for item in state["notes"].values() if item["name"].lower() == lowered]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise sticky_store.StickyError(f"「{token}」という名前の付箋が複数あります。id で指定してください")
    by_prefix = [item for item in state["notes"].values() if item["id"].startswith(token)]
    if len(by_prefix) == 1:
        return by_prefix[0]
    raise sticky_store.StickyError(f"「{token}」という付箋はありません")


def _sid(session_id: str) -> str:
    if not session_id:
        raise sticky_store.StickyError("この会話のidが取れませんでした")
    return sticky_store.session_key(session_id)


def sticky_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    try:
        sid = _sid(session_id)
        token = (raw_args or "").strip()
        state = sticky_store.load()

        if not token:
            notes = sticky_store.notes_for(state, sid)
            if not notes:
                return f"この会話に付箋はありません。\n{USAGE}"
            lines = [f"この会話の付箋 {len(notes)}枚:"]
            for note in notes:
                mark = " · Hermes書き換え可" if state["settings"]["auto_edit"] else " · 提案のみ"
                lines.append(f"  {note['id']}「{note['name']}」rev {note['rev']}{mark}")
                if note["body"]:
                    lines.append(f"    {note['body'][:120]}")
            return "\n".join(lines)

        # An existing note: pin it here.
        try:
            note = _find(state, token)
        except sticky_store.StickyError:
            note = None

        if note:
            state, _ = sticky_store.mutate(lambda current: sticky_store.attach(current, note["id"], sid))
            sticky_inject.mark_dirty(sid)
            here = len(sticky_store.notes_for(state, sid))
            return f"「{note['name']}」({note['id']}) をこの会話に貼りました。この会話の付箋は{here}枚。"

        state, updated = sticky_store.mutate(lambda current: sticky_store.create(current, name=token, pin_to=sid))
        sticky_inject.mark_dirty(sid)
        return f"付箋「{updated['name']}」({updated['id']}) を作ってこの会話に貼りました。/stickyedit で本文を書けます。"
    except sticky_store.StickyError as exc:
        return f"{exc}"
    except Exception as exc:
        logger.warning("sticky command failed", exc_info=True)
        return f"失敗しました: {type(exc).__name__}: {exc}"


def unsticky_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    try:
        sid = _sid(session_id)
        token = (raw_args or "").strip()
        state = sticky_store.load()
        notes = sticky_store.notes_for(state, sid)
        if not notes:
            return "この会話に付箋はありません。"

        if not token:
            if len(notes) == 1:
                target = notes[0]
            else:
                listing = " / ".join(f"{note['id']}「{note['name']}」" for note in notes)
                return f"どの付箋を外しますか: {listing}"
        else:
            target = _find(state, token)

        state, _ = sticky_store.mutate(lambda current: sticky_store.detach(current, target["id"], sid))
        sticky_inject.mark_dirty(sid)
        return f"「{target['name']}」をこの会話から外しました。付箋そのものは残っています。"
    except sticky_store.StickyError as exc:
        return f"{exc}"
    except Exception as exc:
        logger.warning("unsticky command failed", exc_info=True)
        return f"失敗しました: {type(exc).__name__}: {exc}"


def stickyedit_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    try:
        sid = _sid(session_id)
        text = (raw_args or "").strip()
        if not text:
            return "本文を指定してください: /stickyedit 調査メモはここまで"
        state = sticky_store.load()
        notes = sticky_store.notes_for(state, sid)
        if not notes:
            return "この会話に付箋がありません。先に /sticky <名前> で貼ってください。"

        notes_sorted = sorted(notes, key=lambda note: note["updated_at"], reverse=True)
        note = notes_sorted[0]
        if len(notes) > 1:
            explicit = None
            for candidate in notes:
                for prefix in (candidate["id"], candidate["name"]):
                    if text.startswith(prefix + " "):
                        explicit = (candidate, text[len(prefix) + 1 :].strip())
                        break
                if explicit:
                    break
            if explicit:
                note, text = explicit
            else:
                preview = " / ".join(f"{item['id']}「{item['name']}」" for item in notes)
                return (
                    f"付箋が複数あります。いまは「{note['name']}」を書き換えます。"
                    f"別の付箋なら id を頭に付けてください: {preview}\n例: /stickyedit {note['id']} {text[:40]}"
                )
            if not text:
                return "本文が空です。"

        state, updated = sticky_store.mutate(lambda current: sticky_store.set_body(current, note["id"], text, author="user"))
        sticky_inject.mark_dirty(sid)
        return f"「{updated['name']}」を rev {updated['rev']} に書き換えました（この付箋が付いた{len(updated['sessions'])}件の会話に反映されます）。"
    except sticky_store.StickyError as exc:
        return f"{exc}"
    except Exception as exc:
        logger.warning("stickyedit command failed", exc_info=True)
        return f"失敗しました: {type(exc).__name__}: {exc}"


def stickyundo_command(raw_args: str = "", session_id: str = "", **_: Any) -> str:
    try:
        sid = _sid(session_id)
        state = sticky_store.load()
        notes = sticky_store.notes_for(state, sid)
        if not notes:
            return "この会話に付箋がありません。"
        token = (raw_args or "").strip()
        target = _find(state, token) if token else sorted(notes, key=lambda item: item["updated_at"], reverse=True)[0]
        state, note = sticky_store.mutate(lambda current: sticky_store.revert(current, target["id"]))
        sticky_inject.mark_dirty(sid)
        return f"「{note['name']}」を rev {note['rev']} に戻しました。"
    except sticky_store.StickyError as exc:
        return f"{exc}"
    except Exception as exc:
        logger.warning("stickyundo command failed", exc_info=True)
        return f"失敗しました: {type(exc).__name__}: {exc}"
