# Fusen

*Fusen* (付箋) is Japanese for a sticky note. This one lives on your conversations. It is a tag and a note at the same
time: it has a name, a colour, and an **editable body**, and you can pin one note
to as many chats as you like.

```
one note ──┬── chat "pricing page rewrite"
           ├── chat "checkout bug"
           └── chat "2026-11 planning"
```

Rewrite the body once and every chat that carries the note sees it. Hermes can
rewrite it too — with your permission, with a revision history, and with undo.

---

## Why this is not just "tags", and not just "notes"

Hermes already has tags (grouping) and notes (text files). The thing that was
missing is **a note that is attached to a conversation, so the conversation knows
about it without you pasting it again**.

That single design choice gives three behaviours you cannot get from either half:

1. **Context that survives the chat.** Pin "決済まわりは Stripe の webhook で詰まっている"
   to a chat. Two days later the model still knows where you were, even after a
   compaction.
2. **One body, many chats.** The same note pinned to five chats is one file. Fix a
   fact in it and all five see the fix — no copy drift.
3. **Context across chats.** `fusen_notes(action="search", note_id=…)` returns the
   other conversations carrying the same note, and `action="read"` pulls their
   messages. That is how you pick up a thread you dropped three chats ago.

Comparing with the closest catalog entries:

| | fusen | constraint-vault | jot | waypoint | sticky-notes |
|---|---|---|---|---|---|
| free-standing notes | ✓ | ✓ (constraints) | ✓ | ✓ | ✓ |
| attached to a **conversation** | ✓ | — (global) | — | ✓ (as a marker) | optional, UI only |
| one note on **many** chats, one body | ✓ | — | — | — | — |
| injected into the model's turn | ✓ | ✓ | — (agent reads on demand) | — | — |
| injected only when the model's view is stale | ✓ | — (every turn) | n/a | n/a | n/a |
| model can rewrite it, with approval | ✓ | — (pins/drops without asking) | ✓ | — | — |
| find other chats by the same note | ✓ | — | — | — | — |

## Install

```bash
hermes plugins install <repo>          # or: git clone into ~/.hermes/plugins/fusen
hermes plugins enable fusen
```

Restart the gateway. In the Desktop app, enable the package under
**Capabilities → Plugins** (a copied desktop half starts disabled on purpose),
then **⌘K → Fusen: open the panel**.

`requires_hermes: >=0.22.5`.

## Using it

**Pin a note.** The banner above the composer has a `Pin a note` button; the
panel does the same, and `/fusen <name>` does it from the keyboard.

**Rewrite it.** Click the body and type. `⌘↵` saves. Every chat carrying the note
sees the new text on its next turn.

**Ask Hermes to rewrite it.** Say "tighten this note". With *Let Hermes rewrite
note bodies* on, it edits in place and the panel shows `rev 3 · Hermes`. With it
off, Hermes can only file a **proposal**: it appears at the top of the panel with
*Apply* / *Dismiss*, and nothing changes until you press one. Either way, every
revision is kept, and `History` restores any of them.

**Start a chat with a note.** Panel → pin icon on a note → *New chat with this
note*. Hermes opens a draft; the first message you send gets the note attached.

**Pick up a dropped thread.** `⌘K` → the note's name → the palette toggles the pin,
or open the panel and click one of the chats under the note.

### Slash commands

| command | does |
|---|---|
| `/fusen` | list this chat's notes |
| `/fusen <name>` | create a note and pin it here (or pin an existing one) |
| `/unfusen <name\|id>` | unpin (the note itself survives) |
| `/fusenedit <text>` | rewrite the body (all pinned chats follow) |
| `/fusenundo` | roll back one revision |

### Tools

| tool | does |
|---|---|
| `fusen_notes` | `list` this chat's notes / `get` one / `search` the chats sharing a note or notes by text / `read` a chat's messages |
| `fusen_pin` | `attach` / `detach` a note on a chat |
| `fusen_write` | `write` the body (applies or files a proposal), `revert`, `accept`, `discard` |

## How the injection keeps your cache intact

The block is added by `pre_llm_call`, which appends to the **current turn's user
message** — the system prompt is never touched, so everything upstream of this
turn stays byte-identical and the provider's prefix cache keeps hitting.

Adding the block on every turn would still break the prefix, so the gate is
narrow. A turn only gets the block when the model's view is actually stale:

- the chat is new (nothing injected yet),
- the notes changed since they were injected (rewrite, pin, unpin — from this
  process or from a second window),
- a compaction rewrote the history and dropped the block (`post_compaction`),
- the history does not contain the block at all (fresh process, or an old chat
  that predates the plugin).

Every other turn adds nothing. `Settings → When to add notes` exposes the three
modes: `auto` (above), `always`, `off`. Switching modes never changes the tool
list — a tool appearing or disappearing mid-chat would invalidate the prefix, so
the switch only changes what `fusen_write` is *allowed* to do.

Reads are cached on the state file's `(mtime, size)`, so a second process's write
is noticed without polling, and the cost of a repeat read is one `stat()`.

## Settings

| key | default | meaning |
|---|---|---|
| `auto_edit` | on | Hermes may rewrite bodies directly. Off = proposals only. |
| `inject` | `auto` | `auto` / `always` / `off` — when the notes reach the model. |
| `max_chars` | 400 | characters per note in the injected block |
| `max_notes_per_session` | 5 | notes one chat may carry |
| `history_depth` | 10 | revisions kept per note |

## What it reads, writes, and sends

- **Writes:** one JSON file, `plugin_data_dir("fusen")/state.json`
  (`~/.hermes/plugin-data/fusen/state.json`, per profile). Written
  atomically; the last writer re-applies on a fresh read, so the CLI and the
  Desktop cannot clobber each other.
- **Reads:** that file. Conversation titles and start times come from the
  gateway's `session.list`; message text comes from the built-in `session_search`
  tool through `ctx.dispatch_tool`. **The plugin never opens `state.db`.**
- **Network:** none. No telemetry, no remote calls, no API keys.
- **Outside the plugin:** nothing. No core patch; every seam is a documented
  plugin API (`pre_llm_call`, `post_compaction`, `on_session_delete`,
  `register_tool`, `register_command`, `register_hook`, `dispatch_tool`,
  session row slot, `composer.top`, panes, routes, palette, status bar, i18n).

## Known limits

- The composer banner mounts in every composer; with split tiles the chips follow
  the focused chat, not the tile. The panel is the reliable place.
- `host.newChat()` returns no session id, so "new chat with this note" arms a
  claim and attaches once the conversation exists and actually started after the
  press. If you open a *different* chat within a few seconds of the press and
  never send in the draft, the note can land on that chat instead. Unpin it.
- Pane close is the pane chrome (✕); there is no public toggle verb, so the plugin
  models toggling as *reveal* + the pane's own visibility atom.
- Deleting a conversation unpins it (an archive keeps the pin). If a chat was
  deleted while the plugin was uninstalled, the panel shows `deleted`; unpin it
  there.
- Sidebar grouping by note and a right-click "fusen" submenu need core seams
  that do not exist yet, so they are not in this release.

## Development

```
fusen/
├── plugin.yaml            # manifest: tools, hooks, requires_hermes
├── __init__.py            # register()
├── fusen_store.py        # state, revisions, proposals, the ops batch
├── fusen_inject.py       # pre_llm_call gate + compaction/delete hooks
├── fusen_tools.py        # the three tools
├── fusen_commands.py     # /fusen family
├── dashboard/
│   ├── manifest.json      # mounts the REST router
│   └── plugin_api.py      # /state, /ops, /arm
├── desktop/plugin.js      # the desktop half (plain ESM, no build)
└── tests/test_fusen.py   # 49 tests, stdlib only
```

```bash
python -m unittest discover -s tests       # 49 tests, stdlib only
node tools/check-i18n.mjs desktop/plugin.js  # every t('…') key exists in en and ja
hermes plugins validate .
```

The store is plain data (`dict` in, `dict` out) and the ops batch is atomic: a
bad op writes nothing. Add a test with any behaviour change; the injection gate
and the revision semantics are the parts worth protecting.

MIT.
