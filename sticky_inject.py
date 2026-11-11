"""Sticky Tags — what the model is told, and when.

Injection rides ``pre_llm_call``, which appends to the *current turn's user
message*. The system prompt is never touched, so nothing upstream of this turn
changes and the provider's prefix cache keeps hitting.

The gate is the whole point. A turn is repaired only when the model's view is
actually stale:

  * the conversation is new (nothing injected yet),
  * the notes changed since they were last injected (a rewrite, a pin, an
    unpin — from this process or the desktop's HTTP route),
  * a compaction rewrote the history and dropped the block,
  * the history does not contain the block at all (fresh process, or the user
    resumed an old conversation that predates the plugin).

Every other turn adds nothing, so consecutive turns share an identical prefix
and the cache hits. ``settings.inject == "always"`` exists for people who would
rather pay that cost; ``"off"`` sends nothing and leaves the note text to the
sticky_tools.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from . import sticky_store

logger = logging.getLogger(__name__)

MARKER = '<sticky-notes'
MAX_INJECT_CHARS = 6000

# session id → the (note id, rev) pairs the model was last told about
_sent: dict[str, tuple[tuple[str, int], ...]] = {}
# session ids whose history no longer holds the block
_dirty: set[str] = set()
# sessions confirmed to already carry the block in their history
_carries: set[str] = set()


def _history_text(history: Any) -> str:
    """Concatenated text of a conversation history, for the marker check."""
    if not isinstance(history, (list, tuple)):
        return ""
    chunks: list[str] = []
    for message in history:
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, (list, tuple)):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks)


def carries_block(history: Any, sid: str) -> bool:
    if sid in _dirty:
        return False
    if sid in _carries:
        return True
    if MARKER in _history_text(history):
        _carries.add(sid)
        return True
    return False


def mark_dirty(sid: str) -> None:
    """The history no longer holds the block (compaction, reset, edit)."""
    _dirty.add(sid)
    _carries.discard(sid)


def forget(sid: str) -> None:
    _sent.pop(sid, None)
    _dirty.discard(sid)
    _carries.discard(sid)


def should_inject(state: dict[str, Any], sid: str, *, is_first_turn: bool, history: Any) -> bool:
    """Whether this turn needs the block. Pure decision — no side effects."""
    mode = state["settings"]["inject"]
    if mode == "off":
        return False
    if not sticky_store.notes_for(state, sid):
        return False
    if mode == "always":
        return True
    if is_first_turn:
        return True
    if sid in _dirty:
        return True
    if sticky_store.signature(state, sid) != _sent.get(sid):
        # Injected earlier this process and changed since: re-sticky_inject.
        if sid in _sent:
            return True
        # Never injected here: only if the history does not already carry it.
        return not carries_block(history, sid)
    return False


def build(state: dict[str, Any], sid: str) -> str:
    text = sticky_store.render(state, sid)
    if len(text) > MAX_INJECT_CHARS:
        text = text[:MAX_INJECT_CHARS].rstrip() + "\n</sticky-notes>"
    return text


def pre_llm_call(
    session_id: str = "",
    user_message: str = "",
    conversation_history: Any = None,
    is_first_turn: bool = False,
    model: str = "",
    platform: str = "",
    **_: Any,
) -> Optional[dict[str, str]]:
    """Hook body. Returns ``{"context": ...}`` to inject, else None."""
    sid = str(session_id or "")
    if not sid:
        return None
    try:
        state = sticky_store.load()
        if not should_inject(state, sid, is_first_turn=bool(is_first_turn), history=conversation_history):
            return None
        text = build(state, sid)
    except Exception:  # a broken store must never break the user's turn
        logger.warning("sticky-tags: injection skipped", exc_info=True)
        return None

    if not text:
        _sent[sid] = ()
        return None

    _sent[sid] = sticky_store.signature(state, sid)
    _dirty.discard(sid)
    _carries.add(sid)
    return {"context": text}


def post_compaction(session_id: str = "", old_session_id: str = "", **_: Any) -> None:
    """The block was summarized away; put it back on the next turn."""
    for sid in (old_session_id, session_id):
        if sid:
            mark_dirty(str(sid))


def on_session_delete(session_id: str = "", reason: str = "", deleted_ids: Any = None, **_: Any) -> None:
    """Drop deleted conversations from every note. Never raises.

    An archive keeps its row, so the note stays pinned — same rule the tags in
    Hermes core follow.
    """
    if reason == "archive":
        return
    gone = {str(item) for item in (deleted_ids or ()) if item}
    if session_id:
        gone.add(str(session_id))
    if not gone:
        return
    for sid in gone:
        forget(sid)
    try:
        def _prune(state: dict[str, Any]) -> int:
            touched = 0
            for note in state["notes"].values():
                kept = [sid for sid in note["sessions"] if sid not in gone]
                if len(kept) != len(note["sessions"]):
                    note["sessions"] = kept
                    touched += 1
            if not touched:
                raise sticky_store.StickyError("nothing to prune")  # abort the write
            return touched

        sticky_store.mutate(_prune)
    except sticky_store.StickyError:
        return
    except Exception:
        logger.warning("sticky-tags: prune after delete failed", exc_info=True)


def note_changed(sid: str = "") -> None:
    """Any local writer calls this so the next turn re-injects."""
    if sid:
        mark_dirty(sid)
