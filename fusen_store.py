"""Fusen — storage.

A fusen (sticky note) is a tag that carries an editable body. One note can be pinned to
many conversations and one conversation can carry several notes; the body lives
in exactly one place, so a rewrite shows up everywhere the note is pinned.

State is one JSON file in the plugin's data directory (``plugin_data_dir``),
which survives ``hermes plugins update`` and follows the active profile. Reads
are cached on ``(mtime_ns, size)`` so a second process's write is picked up
without polling and a repeat read costs one ``stat()``.

Every mutation re-reads the file inside the lock before applying itself, so two
writers (the desktop's HTTP route and a slash command in the CLI) cannot clobber
each other: the last writer re-applies on top of what it just read.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

PLUGIN_ID = "fusen"
STATE_VERSION = 1

NOTE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

COLORS = ("orange", "blue", "green", "purple", "red", "gray")
DEFAULT_COLOR = "orange"

MAX_NAME = 40
MAX_BODY = 4000

DEFAULT_SETTINGS: dict[str, Any] = {
    # Hermes may rewrite a note body directly when this is on. Off = Hermes can
    # only file a proposal, and the user confirms it.
    "auto_edit": True,
    # auto: inject on the first turn, after a change, and after compaction.
    # always: every turn (breaks prefix caching on purpose). off: never.
    "inject": "auto",
    # Budget per note body in the injected block, in characters.
    "max_chars": 400,
    # Hard cap on notes pinned to one conversation.
    "max_notes_per_session": 5,
    # Revisions kept per note.
    "history_depth": 10,
}

_SETTINGS_LIMITS = {
    "max_chars": (80, 2000),
    "max_notes_per_session": (1, 20),
    "history_depth": (0, 50),
}
_INJECT_MODES = ("auto", "always", "off")


class FusenError(ValueError):
    """A rejected request. Callers turn this into a 400 or an error tool result."""


# ── paths ────────────────────────────────────────────────────────────────


_data_dir_override: Optional[Path] = None


def set_data_dir(path: Any) -> None:
    """Point the store somewhere else (tests, and ``hermes plugins validate``'s scratch home)."""
    global _data_dir_override
    _data_dir_override = Path(path) if path is not None else None
    invalidate()


def data_dir() -> Path:
    """The plugin's durable data directory, following the active profile."""
    if _data_dir_override is not None:
        _data_dir_override.mkdir(parents=True, exist_ok=True)
        return _data_dir_override
    try:
        from plugins.plugin_storage import plugin_data_dir  # documented public helper

        return Path(plugin_data_dir(PLUGIN_ID))
    except Exception:
        home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
        path = Path(home) / "plugins-data" / PLUGIN_ID
        path.mkdir(parents=True, exist_ok=True)
        return path


def state_path() -> Path:
    path = data_dir() / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── parsing helpers ──────────────────────────────────────────────────────


def _now() -> float:
    return round(time.time(), 3)


def _text(value: Any, limit: int, default: str = "") -> str:
    """Single-line-ish text: control characters dropped, whitespace kept, capped."""
    if value is None:
        return default
    text = str(value)
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def _id(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    text = str(value or "").strip()
    if not pattern.match(text):
        raise FusenError(f"invalid {label}: {text[:20]!r}")
    return text


def note_id(value: Any) -> str:
    return _id(value, "note id", NOTE_ID_RE)


def session_key(value: Any) -> str:
    return _id(value, "session id", SESSION_ID_RE)


def new_note_id() -> str:
    return f"n{format(int(time.time() * 1000), 'x')}{os.urandom(2).hex()}"


def _color(value: Any, default: str = DEFAULT_COLOR) -> str:
    text = str(value or "").strip().lower()
    return text if text in COLORS else default


# ── state shape ──────────────────────────────────────────────────────────


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "notes": {},
        "settings": dict(DEFAULT_SETTINGS),
        "updated_at": 0.0,
        # Monotonic counter: ordering must not depend on clock resolution.
        "seq": 0,
    }


def _settings(raw: Any) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key, (low, high) in _SETTINGS_LIMITS.items():
            if key in raw:
                try:
                    out[key] = max(low, min(high, int(raw[key])))
                except (TypeError, ValueError):
                    pass
        if raw.get("inject") in _INJECT_MODES:
            out["inject"] = raw["inject"]
        if "auto_edit" in raw:
            out["auto_edit"] = bool(raw["auto_edit"])
    return out


def _note(raw: Any) -> Optional[dict[str, Any]]:
    """Coerce one stored note, or None when it is unusable."""
    if not isinstance(raw, dict):
        return None
    raw_id = str(raw.get("id") or "")
    if not NOTE_ID_RE.match(raw_id):
        return None
    body = _text(raw.get("body"), MAX_BODY)
    sessions: list[str] = []
    for sid in raw.get("sessions") or ():
        text = str(sid or "")
        if SESSION_ID_RE.match(text) and text not in sessions:
            sessions.append(text)
    history: list[dict[str, Any]] = []
    for entry in raw.get("history") or ():
        if not isinstance(entry, dict):
            continue
        history.append(
            {
                "rev": int(entry.get("rev") or 0),
                "body": _text(entry.get("body"), MAX_BODY),
                "at": float(entry.get("at") or 0),
                "author": "hermes" if entry.get("author") == "hermes" else "user",
            }
        )
    rev = int(raw.get("rev") or 1)
    return {
        "id": raw_id,
        "seq": int(raw.get("seq") or 0),
        "name": _text(raw.get("name"), MAX_NAME) or "note",
        "color": _color(raw.get("color")),
        "body": body,
        "rev": max(1, rev),
        "author": "hermes" if raw.get("author") == "hermes" else "user",
        "created_at": float(raw.get("created_at") or 0),
        "updated_at": float(raw.get("updated_at") or 0),
        "sessions": sessions,
        "history": history[-50:],
    }


def _pending(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    note = str(raw.get("note_id") or "")
    if not NOTE_ID_RE.match(note):
        return None
    return {
        "id": str(raw.get("id") or note)[:64],
        "note_id": note,
        "body": _text(raw.get("body"), MAX_BODY),
        "base_rev": int(raw.get("base_rev") or 0),
        "at": float(raw.get("at") or 0),
        "reason": _text(raw.get("reason"), 200),
        "session_id": str(raw.get("session_id") or "")[:128],
    }


def normalize(raw: Any) -> dict[str, Any]:
    """Turn whatever is on disk into the current shape. Never raises."""
    state = empty_state()
    if not isinstance(raw, dict):
        return state
    notes_raw = raw.get("notes")
    if isinstance(notes_raw, dict):
        for key, value in notes_raw.items():
            note = _note({**value, "id": value.get("id") or key} if isinstance(value, dict) else None)
            if note:
                state["notes"][note["id"]] = note
    elif isinstance(notes_raw, list):
        for value in notes_raw:
            note = _note(value)
            if note:
                state["notes"][note["id"]] = note

    state["settings"] = _settings(raw.get("settings"))
    try:
        state["updated_at"] = float(raw.get("updated_at") or 0)
    except (TypeError, ValueError):
        state["updated_at"] = 0.0
    try:
        state["seq"] = int(raw.get("seq") or 0)
    except (TypeError, ValueError):
        state["seq"] = 0
    # A file written before the counter existed, or hand-edited: derive it.
    state["seq"] = max([state["seq"]] + [note["seq"] for note in state["notes"].values()])

    pending: dict[str, dict[str, Any]] = {}
    for value in raw.get("pending") or ():
        entry = _pending(value)
        if entry and entry["note_id"] in state["notes"]:
            pending[entry["id"]] = entry
    state["pending"] = list(pending.values())
    return state


# ── read cache ───────────────────────────────────────────────────────────

_lock = threading.RLock()
_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def _signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def _read_uncached(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return normalize(json.load(handle))
    except FileNotFoundError:
        return empty_state()
    except (OSError, ValueError):
        return empty_state()


def load() -> dict[str, Any]:
    """The current state. Cached on the file's (mtime, size)."""
    path = state_path()
    key = str(path)
    signature = _signature(path)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    state = _read_uncached(path)
    with _lock:
        _cache[key] = (signature, state)
    return state


def write(state: dict[str, Any]) -> dict[str, Any]:
    """Replace the file atomically (tmp + os.replace) and refresh the cache."""
    path = state_path()
    state = normalize(state)
    state["updated_at"] = _now()
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True)
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    with _lock:
        _cache[str(path)] = (_signature(path), state)
    return state


def mutate(fn: Callable[[dict[str, Any]], Any]) -> tuple[dict[str, Any], Any]:
    """Apply ``fn(state)`` to a FRESH read and persist. Returns (state, result)."""
    with _lock:
        state = _read_uncached(state_path())
        result = fn(state)
        return write(state), result


def invalidate() -> None:
    with _lock:
        _cache.clear()


# ── projections ──────────────────────────────────────────────────────────


def signature(state: dict[str, Any], sid: str) -> tuple[tuple[str, int], ...]:
    """What a conversation would be told: note ids and revisions, in order."""
    return tuple((note["id"], note["rev"]) for note in notes_for(state, sid))


def notes_for(state: dict[str, Any], sid: str) -> list[dict[str, Any]]:
    notes = [note for note in state["notes"].values() if sid in note["sessions"]]
    notes.sort(key=lambda note: (note["seq"], note["created_at"], note["id"]))
    return notes


def sessions_for(state: dict[str, Any], note: dict[str, Any]) -> list[str]:
    return list(note["sessions"])


def payload(state: dict[str, Any], *, sid: str = "") -> dict[str, Any]:
    """The shape the desktop renders."""
    notes = sorted(state["notes"].values(), key=lambda note: (note["seq"], note["created_at"], note["id"]))
    return {
        "version": STATE_VERSION,
        "settings": dict(state["settings"]),
        "updated_at": state["updated_at"],
        "notes": notes,
        "pending": list(state.get("pending") or []),
        "session_note_ids": [note["id"] for note in notes_for(state, sid)] if sid else [],
    }


# ── operations ───────────────────────────────────────────────────────────


def _trim_history(note: dict[str, Any], depth: int) -> None:
    if depth <= 0:
        note["history"] = []
    elif len(note["history"]) > depth:
        note["history"] = note["history"][-depth:]


def _push_history(note: dict[str, Any], body: str, author: str, depth: int) -> None:
    note["history"].append({"rev": note["rev"], "body": body, "at": _now(), "author": author})
    _trim_history(note, depth)


def create(
    state: dict[str, Any],
    *,
    name: str,
    body: str = "",
    color: str = DEFAULT_COLOR,
    pin_to: str = "",
) -> dict[str, Any]:
    clean = _text(name, MAX_NAME)
    if not clean:
        raise FusenError("name is required")
    stamp = _now()
    state["seq"] = int(state.get("seq") or 0) + 1
    note = {
        "id": new_note_id(),
        "seq": state["seq"],
        "name": clean,
        "color": _color(color),
        "body": _text(body, MAX_BODY),
        "rev": 1,
        "author": "user",
        "created_at": stamp,
        "updated_at": stamp,
        "sessions": [],
        "history": [],
    }
    state["notes"][note["id"]] = note
    if pin_to:
        attach(state, note["id"], pin_to)
    return note


def attach(state: dict[str, Any], note_id_: str, sid: str) -> dict[str, Any]:
    note = state["notes"].get(note_id(note_id_))
    if not note:
        raise FusenError("note not found")
    sid = session_key(sid)
    if sid in note["sessions"]:
        return note
    cap = state["settings"]["max_notes_per_session"]
    if len(notes_for(state, sid)) >= cap:
        raise FusenError(f"this conversation already carries {cap} notes")
    note["sessions"].append(sid)
    note["updated_at"] = _now()
    return note


def detach(state: dict[str, Any], note_id_: str, sid: str) -> dict[str, Any]:
    note = state["notes"].get(note_id(note_id_))
    if not note:
        raise FusenError("note not found")
    sid = session_key(sid)
    if sid in note["sessions"]:
        note["sessions"].remove(sid)
        note["updated_at"] = _now()
    return note


def set_body(
    state: dict[str, Any],
    note_id_: str,
    body: Any,
    *,
    author: str = "user",
    expect_rev: Optional[int] = None,
) -> dict[str, Any]:
    """Rewrite a note body. Appends the previous body to history."""
    note = state["notes"].get(note_id(note_id_))
    if not note:
        raise FusenError("note not found")
    if expect_rev is not None and int(expect_rev) != note["rev"]:
        raise FusenError(f"note changed since you read it (rev {note['rev']})")
    text = _text(body, MAX_BODY)
    if text == note["body"]:
        return note
    depth = state["settings"]["history_depth"]
    _push_history(note, note["body"], note["author"], depth)
    note["body"] = text
    note["rev"] += 1
    note["author"] = "hermes" if author == "hermes" else "user"
    note["updated_at"] = _now()
    return note


def update_meta(state: dict[str, Any], note_id_: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Name, colour, order. Not the body — that goes through set_body."""
    note = state["notes"].get(note_id(note_id_))
    if not note:
        raise FusenError("note not found")
    if "name" in patch:
        name = _text(patch["name"], MAX_NAME)
        if not name:
            raise FusenError("name cannot be empty")
        note["name"] = name
    if "color" in patch:
        note["color"] = _color(patch["color"], note["color"])
    note["updated_at"] = _now()
    return note


def delete(state: dict[str, Any], note_id_: str) -> None:
    note = state["notes"].pop(note_id(note_id_), None)
    if note is None:
        raise FusenError("note not found")
    state["pending"] = [entry for entry in state.get("pending") or () if entry["note_id"] != note["id"]]


def revert(state: dict[str, Any], note_id_: str, rev: Optional[int] = None) -> dict[str, Any]:
    """Roll a note back to a stored revision (default: the one before current)."""
    note = state["notes"].get(note_id(note_id_))
    if not note:
        raise FusenError("note not found")
    history = note["history"]
    if not history:
        raise FusenError("no earlier revision to restore")
    if rev is None:
        target = history[-1]
    else:
        match = [entry for entry in history if entry["rev"] == int(rev)]
        if not match:
            raise FusenError(f"revision {rev} is not in history")
        target = match[-1]
    depth = state["settings"]["history_depth"]
    _push_history(note, note["body"], note["author"], depth)
    note["body"] = target["body"]
    note["rev"] += 1
    note["author"] = target["author"]
    note["updated_at"] = _now()
    return note


# ── proposals (auto_edit off) ────────────────────────────────────────────


def propose(
    state: dict[str, Any],
    note_id_: str,
    body: Any,
    *,
    reason: str = "",
    sid: str = "",
) -> dict[str, Any]:
    """File a rewrite the user has to confirm. Replaces any pending one for the note."""
    note = state["notes"].get(note_id(note_id_))
    if not note:
        raise FusenError("note not found")
    entry = {
        "id": os.urandom(4).hex(),
        "note_id": note["id"],
        "body": _text(body, MAX_BODY),
        "base_rev": note["rev"],
        "at": _now(),
        "reason": _text(reason, 200),
        "session_id": str(sid or "")[:128],
    }
    state["pending"] = [item for item in state.get("pending") or () if item["note_id"] != note["id"]]
    state["pending"].append(entry)
    return entry


def accept(state: dict[str, Any], pending_id: str) -> dict[str, Any]:
    entry = next((item for item in state.get("pending") or () if item["id"] == pending_id), None)
    if entry is None:
        raise FusenError("proposal not found")
    note = state["notes"].get(entry["note_id"])
    if not note:
        raise FusenError("note not found")
    state["pending"] = [item for item in state.get("pending") or () if item["id"] != pending_id]
    if entry["base_rev"] != note["rev"]:
        raise FusenError("the note changed after this proposal was filed; discarded")
    set_body(state, note["id"], entry["body"], author="hermes")
    return note


def discard(state: dict[str, Any], pending_id: str) -> None:
    before = len(state.get("pending") or ())
    state["pending"] = [item for item in state.get("pending") or () if item["id"] != pending_id]
    if len(state["pending"]) == before:
        raise FusenError("proposal not found")


def set_settings(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state["settings"])
    merged.update({key: value for key, value in (patch or {}).items() if key in DEFAULT_SETTINGS})
    state["settings"] = _settings(merged)
    return state["settings"]


# ── applying ops (one entry point for the HTTP route and the commands) ────


OPS = {
    "create",
    "update",
    "set_body",
    "revert",
    "attach",
    "detach",
    "delete",
    "settings",
    "accept",
    "discard",
}


def apply(state: dict[str, Any], op: dict[str, Any]) -> None:
    """One change from the wire. Unknown ops are rejected, not ignored."""
    if not isinstance(op, dict):
        raise FusenError("op must be an object")
    kind = str(op.get("op") or "")
    if kind not in OPS:
        raise FusenError(f"unknown op: {kind!r}")

    if kind == "create":
        note = create(
            state,
            name=op.get("name", ""),
            body=op.get("body", ""),
            color=op.get("color", DEFAULT_COLOR),
            pin_to=op.get("pin_to") or "",
        )
        return

    if kind == "settings":
        set_settings(state, op.get("patch") or {})
        return

    if kind == "accept":
        accept(state, str(op.get("pending_id") or ""))
        return

    if kind == "discard":
        discard(state, str(op.get("pending_id") or ""))
        return

    if kind == "delete":
        delete(state, str(op.get("note_id") or ""))
        return

    if kind == "attach":
        attach(state, str(op.get("note_id") or ""), str(op.get("session_id") or ""))
        return

    if kind == "detach":
        detach(state, str(op.get("note_id") or ""), str(op.get("session_id") or ""))
        return

    if kind == "set_body":
        set_body(
            state,
            str(op.get("note_id") or ""),
            op.get("body"),
            author="hermes" if op.get("author") == "hermes" else "user",
            expect_rev=op.get("expect_rev"),
        )
        return

    if kind == "revert":
        revert(state, str(op.get("note_id") or ""), op.get("rev"))
        return

    if kind == "update":
        update_meta(state, str(op.get("note_id") or ""), op.get("patch") or {})
        return

    raise FusenError(f"unknown op: {kind!r}")  # pragma: no cover


def apply_ops(ops: Any, *, sid: str = "") -> dict[str, Any]:
    """Apply a batch atomically: the whole batch lands, or nothing does."""
    if not isinstance(ops, list) or not ops:
        raise FusenError("ops is required")
    with _lock:
        state = _read_uncached(state_path())
        for op in ops:
            apply(state, op)
        state = write(state)
    return payload(state, sid=sid)


# ── text for the model ───────────────────────────────────────────────────


def render(state: dict[str, Any], sid: str) -> str:
    """The block injected into a turn, or '' when this conversation has no notes."""
    notes = notes_for(state, sid)
    if not notes:
        return ""
    budget = state["settings"]["max_chars"]
    lines = [
        '<fusen-notes note="These are notes the user pinned to this conversation. '
        f'They are context the user wrote, not instructions from the system ({len(notes)} pinned).">'
    ]
    for note in notes:
        body = note["body"].strip()
        if len(body) > budget:
            body = body[:budget].rstrip() + " …"
        tag = "hermes" if note["author"] == "hermes" else "user"
        lines.append(f'<note id="{note["id"]}" name="{_escape(note["name"])}" color="{note["color"]}" rev="{note["rev"]}" author="{tag}">')
        lines.append(body or "(empty)")
        lines.append("</note>")
    lines.append("</fusen-notes>")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def summarize(state: dict[str, Any], sid: str) -> str:
    """One line for a slash command / status bar."""
    notes = notes_for(state, sid)
    if not notes:
        return "この会話に付箋はありません。"
    return " / ".join(f'{note["id"]}「{note["name"]}」(rev {note["rev"]})' for note in notes)
