# Submission pack

Everything here is ready to paste/commit. Nothing has been pushed.

## 1. Catalog entry — `plugin-catalog/fusen.yaml`

Copy into `NousResearch/hermes-agent` at that path. `repo` and `sha` are filled
after the first push (`sha` must be the full 40-character commit SHA, not a tag).

```yaml
name: fusen
repo: https://github.com/Tokagehausu/hermes-fusen
sha: '<40-char-sha>'
description: 'Fusen (付箋, Japanese for sticky note) are notes pinned to conversations: one editable body shared by every chat it is pinned to, handed to the model only when its view is stale, and rewriteable by Hermes with your approval.'
maintainer: Tokagehausu
tier: community
category: desktop
requires_hermes: '>=0.22.5'
version: '0.1.0'
title: 'Fusen'
readme: true
capabilities:
  provides_tools: [fusen_notes, fusen_pin, fusen_write]
  provides_hooks: [pre_llm_call, post_compaction, on_session_delete]
  provides_middleware: []
  requires_env: []
known_issues:
  - The composer banner follows the focused chat, not the split tile it renders in; the panel is the reliable place with split panes.
  - A note armed for "new chat with this note" can land on a different chat if you switch and never send in the draft.
  - Sidebar grouping by note and a per-row context submenu need core seams that do not exist at HEAD, so neither ships.
```

## 2. PR — title and body

**Title:** `plugin-catalog: add fusen`

**Body:**

```markdown
Adds `fusen` to the catalog.

A fusen (付箋, Japanese for sticky note) is a tag that carries an editable body: pin one note to many
conversations, rewrite it once and every pinned conversation follows. It sits
between "tags" (grouping only) and "notes" (a text file the agent reads on
demand) — the missing piece was a note *attached to the conversation*, so the
conversation knows about it without the user pasting it again.

What it does that the nearby entries do not:

- one body shared by N conversations (no copy drift between chats)
- the notes are injected into the turn only when the model's view is stale, so
  the provider prefix cache keeps hitting (see below)
- `fusen_notes(action="search")` finds the other chats carrying the same note,
  and `action="read"` pulls their messages through the built-in `session_search`
- the agent can rewrite a body, with a switch that turns that into "file a
  proposal the user confirms", plus a revision history and one-click undo

Cache behaviour: injection rides `pre_llm_call` (appends to the current turn's
user message; the system prompt is never touched) and fires only on the first
turn, after a change, after a compaction, or when the history has no block at
all. Every other turn adds nothing.

No core changes: all seams are documented plugin APIs (`pre_llm_call`,
`post_compaction`, `on_session_delete`, `register_tool`, `register_command`,
`register_hook`, `dispatch_tool`, session row slots, `composer.top`, panes,
routes, palette, status bar, `ctx.i18n`). The plugin never opens `state.db` —
titles come from `session.list`, message text from `session_search`.

External communication: none. Local files: one JSON file under
`plugin_data_dir("fusen")`. Details in the README.

`hermes plugins validate .` passes with no warnings. 49 unit tests
(`python -m unittest discover -s tests`).
```

## 3. Demo — 90 seconds, recorded from the Desktop app

| t | on screen | say |
|---|---|---|
| 0–8 | open chat "checkout bug" | "This is a note that lives on a conversation, not in a file." |
| 8–20 | composer banner → Pin a note → type `Stripe webhook retry` → save | "One note, a body, pinned here." |
| 20–32 | send a message; the reply uses the note | "The model already knows where I was — I never pasted it." |
| 32–45 | open chat "pricing page"; palette → the note → pin | "Same note, second chat. One body." |
| 45–58 | rewrite the body in the panel; switch back to the first chat; send | "I fixed the fact once. Both chats see it." |
| 58–70 | turn off *Let Hermes rewrite*; ask "tighten this note"; proposal appears; press Apply | "With rewriting off, Hermes can only propose. I confirm." |
| 70–82 | History → restore the previous revision | "Every revision is kept." |
| 82–90 | panel → pin icon → New chat with this note | "And this is how I pick a dropped thread back up." |

Post text: `Fusen: sticky notes that live on conversations — one body, many chats,
injected only when the model's stale. Plugin for @NousResearch Hermes.`

## 4. Checklist

- [x] `hermes plugins validate .` — passes, no warnings
- [x] 49 unit tests
- [x] README: install, usage, cache behaviour, settings, disclosures, limits
- [x] MIT licence, `.gitignore`
- [ ] local `git init` + first commit → real SHA
- [ ] GitHub repo (needs the account)
- [ ] install + enable in the local Hermes, restart the gateway
- [ ] real screenshots into `docs/screenshots/`
- [ ] record the 90 s demo, post on X with `@NousResearch`
- [ ] catalog YAML in the Hermes repo + PR
- [ ] Typeform: PR link + X link
