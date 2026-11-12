"""Fusen — text the slash commands show.

English is the default. Japanese is a translation, picked when Hermes' own
language (``display.language`` / ``HERMES_LANGUAGE``) is Japanese. The desktop
half carries its own bundles in ``desktop/plugin.js``; this file is only for the
Python side (command descriptions, command output, command errors).
"""

from __future__ import annotations

import os
from typing import Any, Optional

DEFAULT = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # register_command descriptions and argument hints
        "cmd.fusen": "Pin a note to this chat, or list this chat's notes (no name)",
        "cmd.fusen.hint": "<note name>",
        "cmd.unfusen": "Unpin a note from this chat (the note itself is kept)",
        "cmd.unfusen.hint": "<note name|id>",
        "cmd.fusenedit": "Rewrite a note body (every chat carrying it follows)",
        "cmd.fusenedit.hint": "<new body>",
        "cmd.fusenundo": "Roll a note back one revision",
        "cmd.fusenundo.hint": "<note name|id>",
        "cmd.fusenapply": "Apply a rewrite Hermes proposed",
        "cmd.fusenapply.hint": "<proposal id>",
        "cmd.fusendismiss": "Dismiss a rewrite Hermes proposed",
        "cmd.fusendismiss.hint": "<proposal id>",
        # output
        "usage": (
            "Fusen: /fusen lists, /fusen <name> pins a note here, /unfusen <name|id> unpins, "
            "/fusenedit <text> rewrites, /fusenundo rolls back one, /fusenapply and /fusendismiss settle Hermes' proposals"
        ),
        "item": '{id} "{name}"',
        "none_here": "This chat has no notes.",
        "list_header": "Notes on this chat ({count}):",
        "list_row": '  {id} "{name}" rev {rev}{mark}',
        "mark_auto": " · Hermes may rewrite",
        "mark_propose": " · proposals only",
        "pending_header": "Waiting for you ({count}):",
        "pending_row": '  {id} → "{name}": {excerpt}',
        "pending_hint": "  /fusenapply <id> to apply, /fusendismiss <id> to dismiss",
        "pinned": 'Pinned "{name}" ({id}) to this chat. This chat now carries {count}.',
        "created": 'Created "{name}" ({id}) and pinned it here. Write its body with /fusenedit.',
        "which_unpin": "Which note? {listing}",
        "unpinned": 'Unpinned "{name}" from this chat. The note itself is kept.',
        "edit_need_text": "Give the new body: /fusenedit Research stops here",
        "edit_no_notes": "This chat has no notes. Pin one first with /fusen <name>.",
        "edit_ambiguous": (
            'This chat carries several notes; this would rewrite "{name}". '
            "For another one, put its id first: {listing}\nExample: /fusenedit {id} {text}"
        ),
        "edit_empty": "The body is empty.",
        "edited": 'Rewrote "{name}" to rev {rev} ({count} chat(s) carrying it follow).',
        "undone": 'Rolled "{name}" back; it is now rev {rev}.',
        "applied": 'Applied the proposal to "{name}"; it is now rev {rev}.',
        "dismissed": 'Dismissed the proposal for "{name}".',
        "no_proposals": "No proposal is waiting on this chat's notes.",
        "which_proposal": "Several proposals are waiting. Pass an id: {listing}",
        "failed": "Failed: {error}",
        # errors
        "err.need_name": "Give a note name or id.",
        "err.ambiguous": 'More than one note is named "{token}". Use its id.',
        "err.not_found": 'No note named "{token}".',
        "err.no_session": "Could not get this chat's id.",
        "err.proposal_not_found": 'No proposal "{token}".',
    },
    "ja": {
        "cmd.fusen": "付箋を貼る・一覧する（名前なしでこの会話の付箋）",
        "cmd.fusen.hint": "付箋の名前",
        "cmd.unfusen": "この会話から付箋を外す（付箋そのものは残ります）",
        "cmd.unfusen.hint": "付箋の名前かid",
        "cmd.fusenedit": "付箋の本文を書き換える（全部の会話に反映）",
        "cmd.fusenedit.hint": "本文",
        "cmd.fusenundo": "付箋をひとつ前の版に戻す",
        "cmd.fusenundo.hint": "付箋の名前かid",
        "cmd.fusenapply": "Hermes の書き換え案を適用する",
        "cmd.fusenapply.hint": "案のid",
        "cmd.fusendismiss": "Hermes の書き換え案をやめる",
        "cmd.fusendismiss.hint": "案のid",
        "usage": (
            "付箋: /fusen で一覧、/fusen <名前> でこの会話に貼る、/unfusen <名前|id> で外す、"
            "/fusenedit <本文> で書き換え、/fusenundo でひとつ戻す、/fusenapply と /fusendismiss で Hermes の案を確定"
        ),
        "item": "{id}「{name}」",
        "none_here": "この会話に付箋はありません。",
        "list_header": "この会話の付箋 {count}枚:",
        "list_row": "  {id}「{name}」rev {rev}{mark}",
        "mark_auto": " · Hermes書き換え可",
        "mark_propose": " · 提案のみ",
        "pending_header": "確認待ちの案 {count}件:",
        "pending_row": "  {id} →「{name}」: {excerpt}",
        "pending_hint": "  /fusenapply <id> で適用、/fusendismiss <id> でやめる",
        "pinned": "「{name}」({id}) をこの会話に貼りました。この会話の付箋は{count}枚。",
        "created": "付箋「{name}」({id}) を作ってこの会話に貼りました。/fusenedit で本文を書けます。",
        "which_unpin": "どの付箋を外しますか: {listing}",
        "unpinned": "「{name}」をこの会話から外しました。付箋そのものは残っています。",
        "edit_need_text": "本文を指定してください: /fusenedit 調査メモはここまで",
        "edit_no_notes": "この会話に付箋がありません。先に /fusen <名前> で貼ってください。",
        "edit_ambiguous": (
            "付箋が複数あります。いまは「{name}」を書き換えます。"
            "別の付箋なら id を頭に付けてください: {listing}\n例: /fusenedit {id} {text}"
        ),
        "edit_empty": "本文が空です。",
        "edited": "「{name}」を rev {rev} に書き換えました（この付箋が付いた{count}件の会話に反映されます）。",
        "undone": "「{name}」を rev {rev} に戻しました。",
        "applied": "「{name}」に案を適用しました。rev {rev} です。",
        "dismissed": "「{name}」の案をやめました。",
        "no_proposals": "この会話の付箋に確認待ちの案はありません。",
        "which_proposal": "確認待ちの案が複数あります。id を指定してください: {listing}",
        "failed": "失敗しました: {error}",
        "err.need_name": "付箋の名前かidを指定してください",
        "err.ambiguous": "「{token}」という名前の付箋が複数あります。id で指定してください",
        "err.not_found": "「{token}」という付箋はありません",
        "err.no_session": "この会話のidが取れませんでした",
        "err.proposal_not_found": "「{token}」という案はありません",
    },
}

_override: Optional[str] = None


def set_language(lang: Optional[str]) -> None:
    """Force a language (tests). ``None`` goes back to following Hermes."""
    global _override
    _override = lang


def language() -> str:
    """``ja`` when Hermes is set to Japanese, else ``en``. Never raises.

    Reads ``display.language`` through ``hermes_cli.config`` (a published plugin API);
    ``HERMES_LANGUAGE`` is the per-profile override Hermes itself honours.
    """
    if _override:
        return _override if _override in MESSAGES else DEFAULT
    value = ""
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
        value = str((config.get("display") or {}).get("language") or "")
    except Exception:
        value = ""
    if not value:
        value = os.environ.get("HERMES_LANGUAGE", "")
    base = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in MESSAGES else DEFAULT


def msg(key: str, lang: Optional[str] = None, **kwargs: Any) -> str:
    """The text for ``key``, falling back to English, then to the key itself."""
    table = MESSAGES.get(lang or language()) or MESSAGES[DEFAULT]
    text = table.get(key) or MESSAGES[DEFAULT].get(key) or key
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text
