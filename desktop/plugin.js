/**
 * Sticky Tags — desktop half.
 *
 * A note is a tag that carries a body: pin one note to many conversations, pin
 * several notes to one conversation, rewrite the body once and every pinned
 * conversation sees it.
 *
 *   - sidebar row: one dot per note, plus a count      [SESSION_ROW_AREAS]
 *   - composer banner: the notes this chat carries    [composer.top]
 *   - right pane: read, rewrite, history, siblings    [panes]
 *   - page + palette + status bar                     [routes/palette/statusBar]
 *
 * Data lives in the backend (../dashboard/plugin_api.py) so the CLI's /sticky
 * commands and the panel write the same file. Every write is a batch of ops;
 * the answer is the new state, which is what gets painted.
 */

import {
  atom,
  Button,
  Codicon,
  ColorSwatches,
  COMPOSER_AREAS,
  computed,
  host,
  Input,
  PANES_AREA,
  PALETTE_AREA,
  Popover,
  PopoverContent,
  PopoverTrigger,
  relativeTime,
  ROUTES_AREA,
  SESSION_ROW_AREAS,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  Switch,
  Tip,
  usePluginI18n,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

const ID = 'sticky-tags'
const PAGE = '/sticky-tags'
const PANE = `${ID}:notes`

const SWATCHES = ['orange', 'blue', 'green', 'purple', 'red', 'gray']
const SWATCH_COLOR = {
  orange: 'var(--ui-orange)',
  blue: 'var(--ui-blue)',
  green: 'var(--ui-green)',
  purple: 'var(--ui-purple)',
  red: 'var(--ui-red)',
  gray: 'var(--ui-text-tertiary)'
}

// ── i18n ─────────────────────────────────────────────────────────────────

const STRINGS = {
  en: {
    pane: { title: 'Sticky notes' },
    bar: {
      pin: 'Pin a note',
      none: 'No note on this chat',
      create: 'New note…',
      detach: 'Unpin from this chat'
    },
    page: {
      title: 'Sticky notes',
      lead: 'A note is a tag with a body. Pin it to as many chats as you like; rewrite it once and every chat that carries it sees the change.',
      new: 'New note',
      name: 'Name',
      body: 'Body',
      empty: 'No notes yet.',
      all: 'All notes',
      settings: 'Settings',
      auto_edit: 'Let Hermes rewrite note bodies',
      auto_edit_hint: 'Off: Hermes can only file a proposal, and you confirm it here.',
      inject: 'When to add notes to the model',
      inject_auto: 'When they change (keeps the prompt cache)',
      inject_always: 'Every turn',
      inject_off: 'Never',
      budget: 'Characters per note sent to the model',
      cap: 'Notes per conversation',
      history: 'Revisions kept',
      proposals: 'Waiting for you'
    },
    note: {
      save: 'Save',
      cancel: 'Cancel',
      rev: 'rev',
      by_hermes: 'Hermes wrote this',
      by_user: 'You wrote this',
      restore: 'Restore',
      sessions: 'Chats carrying this note',
      no_sessions: 'Not pinned to any chat yet.',
      deleted: 'deleted',
      detach: 'Unpin',
      delete: 'Delete note',
      color: 'Colour',
      new_chat: 'New chat with this note',
      empty_body: 'No body yet — type one.',
      accept: 'Apply',
      discard: 'Dismiss',
      proposed: 'Hermes suggests a rewrite'
    },
    toast: {
      saved: 'Saved',
      pinned: 'Pinned to this chat',
      detached: 'Unpinned',
      created: 'Note created',
      failed: 'Could not save the note',
      claim: 'Note pinned to the new chat'
    }
  },
  ja: {
    pane: { title: '付箋' },
    bar: {
      pin: '付箋を貼る',
      none: 'この会話に付箋はありません',
      create: '新しい付箋…',
      detach: 'この会話から外す'
    },
    page: {
      title: '付箋',
      lead: '付箋は本文を持つタグです。何件の会話にでも貼れます。本文を1回書き換えれば、貼った全会話に反映されます。',
      new: '新しい付箋',
      name: '名前',
      body: '本文',
      empty: '付箋はまだありません。',
      all: 'すべての付箋',
      settings: '設定',
      auto_edit: 'Hermes に本文の書き換えを許す',
      auto_edit_hint: 'オフ: Hermes は案を出すだけで、ここで確定します。',
      inject: 'モデルに渡すタイミング',
      inject_auto: '変わった時だけ（プロンプトのキャッシュを保つ）',
      inject_always: '毎ターン',
      inject_off: '渡さない',
      budget: '1枚あたりモデルに渡す文字数',
      cap: '1会話に貼れる枚数',
      history: '残す版の数',
      proposals: '確認待ち'
    },
    note: {
      save: '保存',
      cancel: 'やめる',
      rev: '版',
      by_hermes: 'Hermes が書き換え',
      by_user: '自分で記入',
      restore: 'この版に戻す',
      sessions: 'この付箋を貼った会話',
      no_sessions: 'まだどの会話にも貼っていません。',
      deleted: '削除済み',
      detach: '外す',
      delete: '付箋を削除',
      color: '色',
      new_chat: 'この付箋で新しい会話',
      empty_body: '本文はまだありません。',
      accept: '適用',
      discard: 'やめる',
      proposed: 'Hermes の書き換え案'
    },
    toast: {
      saved: '保存しました',
      pinned: 'この会話に貼りました',
      detached: '外しました',
      created: '付箋を作りました',
      failed: '付箋を保存できませんでした',
      claim: '新しい会話に付箋を貼りました'
    }
  }
}

// ── store ────────────────────────────────────────────────────────────────

const EMPTY = { notes: [], pending: [], settings: {}, session_note_ids: [], updated_at: 0 }

const $data = atom(EMPTY)
const $sessions = atom({}) // session id → { title, last_active, archived, exists }
const $status = atom({ error: null, loaded: false })

let restCtx = null
let queue = Promise.resolve()
let pendingWrites = 0
let lastWrite = 0

const noteById = (data, id) => data.notes.find(note => note.id === id) || null
const notesOnSession = (data, sid) => (sid ? data.notes.filter(note => note.sessions.includes(sid)) : [])

function apply(payload) {
  if (!payload || !Array.isArray(payload.notes)) {
    return
  }
  $data.set({
    notes: payload.notes,
    pending: payload.pending || [],
    settings: payload.settings || {},
    session_note_ids: payload.session_note_ids || [],
    updated_at: payload.updated_at || 0
  })
  $status.set({ error: null, loaded: true })
}

function focusedSession() {
  return host.state.focusedStoredSessionId.get() || ''
}

async function load() {
  if (!restCtx) {
    return
  }
  try {
    const sid = focusedSession()
    apply(await restCtx.rest(`/state${sid ? `?session_id=${encodeURIComponent(sid)}` : ''}`))
    void resolveTitles()
  } catch (err) {
    $status.set({ ...$status.get(), error: String(err?.message || err), loaded: true })
  }
}

// Titles come from the gateway's own session list (`session.list`), not from our
// backend: the store only holds ids, and this keeps the plugin off state.db.
let sessionRows = []

async function resolveTitles() {
  try {
    const payload = await host.request('session.list', { limit: 250 })
    const rows = payload?.sessions || []
    sessionRows = rows
    const map = {}
    for (const row of rows) {
      const info = {
        archived: Boolean(row.archived),
        exists: true,
        last_active: row.last_active || row.started_at || 0,
        started_at: row.started_at || 0,
        title: row.title || ''
      }
      map[row.id] = info
      // A compressed conversation keeps its lineage-root id in the sidebar.
      if (row._lineage_root_id && !map[row._lineage_root_id]) {
        map[row._lineage_root_id] = info
      }
    }
    $sessions.set(map)
  } catch {
    // titles are cosmetic; ids still work
  }
}

// Optimistic: paint the change, send the ops in order, settle on the answer.
function commit(ops, { optimistic } = {}) {
  if (optimistic) {
    $data.set({ ...$data.get(), ...optimistic })
  }
  pendingWrites += 1
  queue = queue.then(async () => {
    try {
      const sid = focusedSession()
      const payload = await restCtx.rest('/ops', {
        body: { ops, session_id: sid || undefined },
        method: 'POST'
      })
      lastWrite = payload?.updated_at || 0
      if (pendingWrites === 1) {
        apply(payload)
        void resolveTitles()
      }
    } catch (err) {
      host.notifyError(err, t('toast.failed'))
      await load()
    } finally {
      pendingWrites -= 1
    }
  })
  return queue
}

function op(name, extra) {
  return { op: name, ...extra }
}

const createNote = (name, color, pinTo) =>
  commit([op('create', { name, color, pin_to: pinTo || null })])

const setBody = (noteId, body, expectRev, author) =>
  commit([op('set_body', { note_id: noteId, body, expect_rev: expectRev, author: author || 'user' })])

const updateMeta = (noteId, patch) => commit([op('update', { note_id: noteId, patch })])
const revertNote = (noteId, rev) => commit([op('revert', { note_id: noteId, rev })])
const attachNote = (noteId, sid) => commit([op('attach', { note_id: noteId, session_id: sid })])
const detachNote = (noteId, sid) => commit([op('detach', { note_id: noteId, session_id: sid })])
const deleteNote = noteId => commit([op('delete', { note_id: noteId })])
const setSettings = patch => commit([op('settings', { patch })])
const acceptPending = pendingId => commit([op('accept', { pending_id: pendingId })])
const discardPending = pendingId => commit([op('discard', { pending_id: pendingId })])

// ── new chat carrying a note ─────────────────────────────────────────────
//
// host.newChat() opens a draft and returns nothing; the session id appears only
// when the first message lands. So: remember when the button was pressed, watch
// the focused durable id, and let the backend claim the first candidate that
// actually STARTED after that.

const CLAIM_EVERY_MS = 3000
const CLAIM_FOR_MS = 30 * 60 * 1000

let claim = null // { noteId, since, startFocus, candidates: Set }

function armNewChat(noteId) {
  const since = Date.now() / 1000
  claim = { noteId, since, startFocus: focusedSession(), candidates: new Set() }
  restCtx
    .rest('/arm', { body: { note_id: noteId, since }, method: 'POST' })
    .then(() => host.newChat())
    .catch(err => {
      claim = null
      host.notifyError(err, t('toast.failed'))
    })
}

function noteFocus(sid) {
  if (claim && sid && sid !== claim.startFocus) {
    claim.candidates.add(sid)
  }
}

async function claimTick() {
  const armed = claim
  if (!armed || !restCtx) {
    return
  }
  if (Date.now() / 1000 - armed.since > CLAIM_FOR_MS / 1000) {
    claim = null
    return
  }
  await resolveTitles()

  for (const sid of [...armed.candidates]) {
    const row = sessionRows.find(item => item.id === sid || item._lineage_root_id === sid)
    if (!row) {
      continue // the row is not written yet — ask again next tick
    }
    const started = Number(row.started_at || 0)
    if (started && started < armed.since - 30) {
      armed.candidates.delete(sid) // an old chat the user merely switched to
      continue
    }
    claim = null
    await attachNote(armed.noteId, sid)
    host.notify({ durationMs: 2200, kind: 'success', message: t('toast.claim') })
    return
  }
}

let t = key => (typeof key === 'string' ? key : '')

function useT() {
  t = usePluginI18n(ID)
  return t
}

// ── host atoms ───────────────────────────────────────────────────────────

function useHostAtom(readable) {
  const [value, setValue] = useState(() => readable.get())
  useEffect(() => readable.subscribe(setValue), [readable])
  return value
}

// ── small pieces ─────────────────────────────────────────────────────────

const dot = (color, size = 8, extra) =>
  jsx('span', {
    'aria-hidden': true,
    style: {
      backgroundColor: SWATCH_COLOR[color] || 'var(--ui-text-tertiary)',
      borderRadius: 9999,
      display: 'inline-block',
      flexShrink: 0,
      height: size,
      width: size,
      ...extra
    }
  })

const hint = { color: 'var(--ui-text-tertiary)', fontSize: 11 }

function ColorPicker({ color, onChange, label }) {
  const [open, setOpen] = useState(false)

  return jsxs(Popover, {
    onOpenChange: setOpen,
    open,
    children: [
      jsx(PopoverTrigger, {
        asChild: true,
        children: jsx('button', {
          'aria-label': label,
          style: {
            alignItems: 'center',
            background: 'transparent',
            border: 0,
            cursor: 'pointer',
            display: 'inline-flex',
            height: 24,
            justifyContent: 'center',
            padding: 0,
            width: 24
          },
          type: 'button',
          children: dot(color, 14)
        })
      }),
      jsx(PopoverContent, {
        align: 'start',
        className: 'w-auto p-2',
        children: jsx(ColorSwatches, {
          onChange: next => {
            onChange(colorFromSwatch(next))
            setOpen(false)
          },
          swatches: SWATCHES.map(name => SWATCH_COLOR[name]),
          value: SWATCH_COLOR[color] || null
        })
      })
    ]
  })
}

const colorFromSwatch = hex => {
  const entry = Object.entries(SWATCH_COLOR).find(([, value]) => value === hex)
  return entry ? entry[0] : 'orange'
}

function PendingCard({ entry }) {
  const data = useValue($data)
  const note = noteById(data, entry.note_id)
  if (!note) {
    return null
  }

  return jsxs('div', {
    style: {
      background: 'var(--ui-bg-secondary)',
      border: '1px solid var(--ui-stroke-secondary)',
      borderLeft: `3px solid ${SWATCH_COLOR[note.color] || 'var(--ui-accent)'}`,
      borderRadius: 8,
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      padding: 10
    },
    children: [
      jsxs('div', {
        style: { alignItems: 'center', display: 'flex', gap: 6 },
        children: [
          jsx(Codicon, { name: 'sparkle', size: '0.875rem' }),
          jsx('span', { style: { fontSize: 12, fontWeight: 600 }, children: t('note.proposed') }),
          jsx('span', { style: { ...hint, marginLeft: 'auto' }, children: `「${note.name}」` })
        ]
      }),
      entry.reason ? jsx('div', { style: hint, children: entry.reason }) : null,
      jsx('div', {
        style: { fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap' },
        children: entry.body || t('note.empty_body')
      }),
      jsxs('div', {
        style: { display: 'flex', gap: 6, justifyContent: 'flex-end' },
        children: [
          jsx(Button, { onClick: () => void discardPending(entry.id), size: 'xs', variant: 'ghost', children: t('note.discard') }),
          jsx(Button, { onClick: () => void acceptPending(entry.id), size: 'xs', children: t('note.accept') })
        ]
      })
    ]
  })
}

// ── sidebar row dots ─────────────────────────────────────────────────────

function RowDots({ sessionId }) {
  const data = useValue($data)
  const notes = notesOnSession(data, sessionId)
  if (!notes.length) {
    return null
  }
  const shown = notes.slice(0, 3)

  return jsx(Tip, {
    label: notes.map(note => note.name).join(' / '),
    children: jsxs('span', {
      style: { alignItems: 'center', display: 'inline-flex', flexShrink: 0, gap: 2, paddingInline: 2 },
      children: [
        ...shown.map(note => jsx(Fragment, { children: dot(note.color, 6) }, note.id)),
        notes.length > shown.length
          ? jsx('span', { style: { ...hint, fontSize: 10 }, children: `+${notes.length - shown.length}` })
          : null
      ]
    })
  })
}

// ── composer banner ──────────────────────────────────────────────────────

function ComposerChips() {
  const data = useValue($data)
  const sid = useHostAtom(host.state.focusedStoredSessionId)
  const notes = notesOnSession(data, sid)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')

  if (!sid) {
    return null
  }

  const unpinned = data.notes.filter(note => !note.sessions.includes(sid))

  const create = () => {
    const clean = name.trim()
    if (!clean) {
      return
    }
    void createNote(clean, 'orange', sid).then(() => host.notify({ durationMs: 1600, kind: 'success', message: t('toast.created') }))
    setName('')
    setOpen(false)
  }

  return jsxs('div', {
    style: { alignItems: 'center', display: 'flex', flexWrap: 'wrap', gap: 6, paddingBottom: 2 },
    children: [
      ...notes.map(note =>
        jsxs(
          'span',
          {
            style: {
              alignItems: 'center',
              background: 'var(--ui-bg-secondary)',
              border: '1px solid var(--ui-stroke-secondary)',
              borderRadius: 9999,
              display: 'inline-flex',
              fontSize: 11,
              gap: 5,
              maxWidth: 240,
              padding: '2px 4px 2px 8px'
            },
            children: [
              dot(note.color, 6),
              jsx('button', {
                onClick: () => host.navigate(PAGE),
                style: {
                  background: 'transparent',
                  border: 0,
                  color: 'inherit',
                  cursor: 'pointer',
                  font: 'inherit',
                  maxWidth: 180,
                  overflow: 'hidden',
                  padding: 0,
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                },
                title: note.body || note.name,
                type: 'button',
                children: note.name
              }),
              jsx(Button, {
                'aria-label': t('bar.detach'),
                onClick: () => void detachNote(note.id, sid),
                size: 'icon-xs',
                variant: 'ghost',
                children: jsx(Codicon, { name: 'close', size: '0.75rem' })
              })
            ]
          },
          note.id
        )
      ),
      jsxs(Popover, {
        onOpenChange: setOpen,
        open,
        children: [
          jsx(PopoverTrigger, {
            asChild: true,
            children: jsxs('button', {
              style: {
                alignItems: 'center',
                background: 'transparent',
                border: '1px dashed var(--ui-stroke-secondary)',
                borderRadius: 9999,
                color: 'var(--ui-text-secondary)',
                cursor: 'pointer',
                display: 'inline-flex',
                fontSize: 11,
                gap: 4,
                padding: '2px 8px'
              },
              type: 'button',
              children: [jsx(Codicon, { name: 'pin', size: '0.75rem' }), t('bar.pin')]
            })
          }),
          jsx(PopoverContent, {
            align: 'start',
            className: 'w-64 p-2',
            children: jsxs('div', {
              style: { display: 'flex', flexDirection: 'column', gap: 4 },
              children: [
                ...unpinned.slice(0, 8).map(note =>
                  jsxs(
                    'button',
                    {
                      onClick: () => {
                        void attachNote(note.id, sid)
                        setOpen(false)
                      },
                      style: {
                        alignItems: 'center',
                        background: 'transparent',
                        border: 0,
                        borderRadius: 6,
                        color: 'inherit',
                        cursor: 'pointer',
                        display: 'flex',
                        fontSize: 12,
                        gap: 6,
                        padding: '4px 6px',
                        textAlign: 'left',
                        width: '100%'
                      },
                      type: 'button',
                      children: [dot(note.color, 8), jsx('span', { children: note.name })]
                    },
                    note.id
                  )
                ),
                unpinned.length ? jsx('div', { style: { borderTop: '1px solid var(--ui-stroke-secondary)' } }) : null,
                jsxs('div', {
                  style: { alignItems: 'center', display: 'flex', gap: 4 },
                  children: [
                    jsx(Input, {
                      'aria-label': t('page.name'),
                      onChange: event => setName(event.target.value),
                      onKeyDown: event => {
                        if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                          create()
                        }
                      },
                      placeholder: t('bar.create'),
                      style: { flex: 1, minWidth: 0 },
                      value: name
                    }),
                    jsx(Button, { disabled: !name.trim(), onClick: create, size: 'xs', children: '+' })
                  ]
                })
              ]
            })
          })
        ]
      })
    ]
  })
}

// ── right pane ───────────────────────────────────────────────────────────

function NoteCard({ note, sid, compact }) {
  const sessions = useValue($sessions)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(note.body)
  const [nameDraft, setNameDraft] = useState(note.name)
  const [historyOpen, setHistoryOpen] = useState(false)

  useEffect(() => {
    setDraft(note.body)
    setNameDraft(note.name)
    setEditing(false)
  }, [note.id, note.rev])

  const dirty = draft !== note.body
  const save = () => {
    if (!dirty) {
      setEditing(false)
      return
    }
    void setBody(note.id, draft, note.rev, 'user').then(() => host.notify({ durationMs: 1400, kind: 'success', message: t('toast.saved') }))
    setEditing(false)
  }

  const members = note.sessions.map(id => [id, sessions[id] || { exists: true }])

  return jsxs('div', {
    style: {
      background: 'var(--ui-bg-secondary)',
      border: '1px solid var(--ui-stroke-secondary)',
      borderLeft: `3px solid ${SWATCH_COLOR[note.color] || 'var(--ui-accent)'}`,
      borderRadius: 10,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      padding: 10
    },
    children: [
      jsxs('div', {
        style: { alignItems: 'center', display: 'flex', gap: 6 },
        children: [
          jsx(ColorPicker, {
            color: note.color,
            label: t('note.color'),
            onChange: next => void updateMeta(note.id, { color: next })
          }),
          editing
            ? jsx(Input, {
                'aria-label': t('page.name'),
                autoFocus: true,
                onBlur: () => {
                  const clean = nameDraft.trim()
                  if (clean && clean !== note.name) {
                    void updateMeta(note.id, { name: clean })
                  } else {
                    setNameDraft(note.name)
                  }
                },
                onChange: event => setNameDraft(event.target.value),
                onKeyDown: event => {
                  if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                    event.currentTarget.blur()
                  }
                },
                style: { flex: 1, minWidth: 0 },
                value: nameDraft
              })
            : jsx('button', {
                onClick: () => setEditing(true),
                style: {
                  background: 'transparent',
                  border: 0,
                  color: 'inherit',
                  cursor: 'text',
                  flex: 1,
                  font: 'inherit',
                  fontSize: 12,
                  fontWeight: 600,
                  minWidth: 0,
                  overflow: 'hidden',
                  padding: 0,
                  textAlign: 'left',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                },
                title: note.name,
                type: 'button',
                children: note.name
              }),
          jsx(Tip, {
            label: note.author === 'hermes' ? t('note.by_hermes') : t('note.by_user'),
            children: jsx('span', {
              style: { ...hint, whiteSpace: 'nowrap' },
              children: `${t('note.rev')} ${note.rev}${note.author === 'hermes' ? ' · Hermes' : ''}`
            })
          })
        ]
      }),
      editing || draft !== note.body
        ? jsx('textarea', {
            'aria-label': t('page.body'),
            autoFocus: editing,
            onChange: event => setDraft(event.target.value),
            onKeyDown: event => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                save()
              }
            },
            rows: Math.min(10, Math.max(2, Math.ceil(draft.length / 46))),
            style: {
              background: 'var(--ui-bg-input)',
              border: '1px solid var(--ui-stroke-secondary)',
              borderRadius: 6,
              color: 'inherit',
              fontFamily: 'inherit',
              fontSize: 12,
              lineHeight: 1.5,
              padding: 6,
              resize: 'vertical',
              width: '100%'
            },
            value: draft
          })
        : jsx('div', {
            onClick: () => setEditing(true),
            style: {
              cursor: 'text',
              fontSize: 12,
              lineHeight: 1.55,
              minHeight: 20,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word'
            },
            children: note.body || jsx('span', { style: hint, children: t('note.empty_body') })
          }),
      dirty
        ? jsxs('div', {
            style: { display: 'flex', gap: 4, justifyContent: 'flex-end' },
            children: [
              jsx(Button, {
                onClick: () => {
                  setDraft(note.body)
                  setEditing(false)
                },
                size: 'xs',
                variant: 'ghost',
                children: t('note.cancel')
              }),
              jsx(Button, { onClick: save, size: 'xs', children: t('note.save') })
            ]
          })
        : jsxs('div', {
            style: { alignItems: 'center', display: 'flex', gap: 2 },
            children: [
              jsx(Tip, {
                label: t('note.sessions'),
                children: jsxs('span', {
                  style: { ...hint, alignItems: 'center', display: 'inline-flex', gap: 4 },
                  children: [jsx(Codicon, { name: 'comment-discussion', size: '0.75rem' }), note.sessions.length]
                })
              }),
              jsx('span', { style: { flex: 1 } }),
              note.history.length
                ? jsxs(Popover, {
                    onOpenChange: setHistoryOpen,
                    open: historyOpen,
                    children: [
                      jsx(PopoverTrigger, {
                        asChild: true,
                        children: jsx(Button, {
                          size: 'icon-xs',
                          variant: 'ghost',
                          children: jsx(Codicon, { name: 'history', size: '0.875rem' })
                        })
                      }),
                      jsx(PopoverContent, {
                        align: 'end',
                        className: 'w-72 p-2',
                        children: jsx('div', {
                          style: { display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 260, overflowY: 'auto' },
                          children: note.history
                            .slice()
                            .reverse()
                            .map(entry =>
                              jsxs(
                                'div',
                                {
                                  style: { borderBottom: '1px solid var(--ui-stroke-secondary)', paddingBottom: 4 },
                                  children: [
                                    jsxs('div', {
                                      style: { ...hint, alignItems: 'center', display: 'flex', gap: 6 },
                                      children: [
                                        jsx('span', { children: `${t('note.rev')} ${entry.rev}` }),
                                        jsx('span', { children: entry.author === 'hermes' ? 'Hermes' : 'you' }),
                                        jsx('span', { style: { flex: 1 } }),
                                        jsx(Button, {
                                          onClick: () => {
                                            void revertNote(note.id, entry.rev)
                                            setHistoryOpen(false)
                                          },
                                          size: 'xs',
                                          variant: 'ghost',
                                          children: t('note.restore')
                                        })
                                      ]
                                    }),
                                    jsx('div', {
                                      style: { fontSize: 11, lineHeight: 1.4, opacity: 0.8, whiteSpace: 'pre-wrap' },
                                      children: entry.excerpt || '—'
                                    })
                                  ]
                                },
                                `${entry.rev}-${entry.at}`
                              )
                            )
                        })
                      })
                    ]
                  })
                : null,
              jsxs(Popover, {
                children: [
                  jsx(PopoverTrigger, {
                    asChild: true,
                    children: jsx(Button, {
                      size: 'icon-xs',
                      variant: 'ghost',
                      children: jsx(Codicon, { name: 'pin', size: '0.875rem' })
                    })
                  }),
                  jsx(PopoverContent, {
                    align: 'end',
                    className: 'w-72 p-2',
                    children: jsxs('div', {
                      style: { display: 'flex', flexDirection: 'column', gap: 4 },
                      children: [
                        jsxs('div', {
                          style: { ...hint, display: 'flex', justifyContent: 'space-between' },
                          children: [jsx('span', { children: t('note.sessions') }), jsx('span', { children: note.sessions.length })]
                        }),
                        members.length
                          ? members.map(([id, meta]) =>
                              jsxs(
                                'div',
                                {
                                  style: { alignItems: 'center', display: 'flex', fontSize: 12, gap: 4, minWidth: 0 },
                                  children: [
                                    jsx('button', {
                                      disabled: meta.exists === false,
                                      onClick: () => host.openSession(id),
                                      style: {
                                        background: 'transparent',
                                        border: 0,
                                        color: 'inherit',
                                        cursor: 'pointer',
                                        flex: 1,
                                        font: 'inherit',
                                        minWidth: 0,
                                        opacity: meta.exists === false ? 0.5 : 1,
                                        overflow: 'hidden',
                                        padding: '2px 0',
                                        textAlign: 'left',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap'
                                      },
                                      title: meta.title || id,
                                      type: 'button',
                                      children: meta.title || (meta.exists === false ? t('note.deleted') : id)
                                    }),
                                    meta.last_active
                                      ? jsx('span', { style: { ...hint, whiteSpace: 'nowrap' }, children: relativeTime(meta.last_active * 1000) })
                                      : null,
                                    jsx(Button, {
                                      onClick: () => void detachNote(note.id, id),
                                      size: 'icon-xs',
                                      variant: 'ghost',
                                      children: jsx(Codicon, { name: 'close', size: '0.75rem' })
                                    })
                                  ]
                                },
                                id
                              )
                            )
                          : jsx('div', { style: hint, children: t('note.no_sessions') }),
                        jsx('div', { style: { borderTop: '1px solid var(--ui-stroke-secondary)', paddingTop: 4 } }),
                        jsxs(Button, {
                          onClick: () => armNewChat(note.id),
                          size: 'xs',
                          variant: 'ghost',
                          children: [jsx(Codicon, { name: 'add', size: '0.875rem' }), t('note.new_chat')]
                        })
                      ]
                    })
                  })
                ]
              }),
              sid
                ? jsx(Button, {
                    'aria-label': t('note.detach'),
                    onClick: () => void detachNote(note.id, sid),
                    size: 'icon-xs',
                    variant: 'ghost',
                    children: jsx(Codicon, { name: 'close' })
                  })
                : null,
              compact
                ? null
                : jsx(Button, {
                    'aria-label': t('note.delete'),
                    onClick: () => {
                      if (window.confirm(`${t('note.delete')}: ${note.name}`)) {
                        void deleteNote(note.id)
                      }
                    },
                    size: 'icon-xs',
                    variant: 'ghost',
                    children: jsx(Codicon, { name: 'trash' })
                  })
            ]
          })
    ]
  })
}

function NotesPane() {
  useT()
  const data = useValue($data)
  const status = useValue($status)
  const sid = useHostAtom(host.state.focusedStoredSessionId)
  const notes = notesOnSession(data, sid)
  const proposals = data.pending.filter(entry => !sid || entry.session_id === sid || !entry.session_id)

  useEffect(() => {
    if (!status.loaded) {
      void load()
    }
  }, [status.loaded])

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 8, height: '100%', overflowY: 'auto', padding: 10 },
    children: [
      jsxs('div', {
        style: { alignItems: 'center', display: 'flex', gap: 6 },
        children: [
          jsx('span', { style: { fontSize: 12, fontWeight: 600 }, children: t('pane.title') }),
          jsx('span', { style: hint, children: sid ? String(notes.length) : '' }),
          jsx('span', { style: { flex: 1 } }),
          jsx(Button, {
            onClick: () => host.navigate(PAGE),
            size: 'icon-xs',
            variant: 'ghost',
            children: jsx(Codicon, { name: 'settings-gear', size: '0.875rem' })
          })
        ]
      }),
      status.error ? jsx('div', { style: { ...hint, color: 'var(--ui-red)' }, children: status.error }) : null,
      ...proposals.map(entry => jsx(PendingCard, { entry }, entry.id)),
      sid
        ? notes.length
          ? notes.map(note => jsx(NoteCard, { note, sid }, note.id))
          : jsx('div', { style: { ...hint, paddingTop: 8 }, children: t('bar.none') })
        : jsx('div', { style: { ...hint, paddingTop: 8 }, children: '—' })
    ]
  })
}

// ── page ─────────────────────────────────────────────────────────────────

function Settings() {
  const data = useValue($data)
  const settings = data.settings || {}
  const num = (key, value) => setSettings({ [key]: Number(value) })

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 10 },
    children: [
      jsx('div', { style: { fontSize: 12, fontWeight: 600 }, children: t('page.settings') }),
      jsxs('label', {
        style: { alignItems: 'center', display: 'flex', gap: 8 },
        children: [
          jsx(Switch, {
            checked: Boolean(settings.auto_edit),
            onCheckedChange: auto_edit => void setSettings({ auto_edit }),
            size: 'xs'
          }),
          jsxs('span', {
            style: { display: 'flex', flexDirection: 'column' },
            children: [
              jsx('span', { style: { fontSize: 12 }, children: t('page.auto_edit') }),
              jsx('span', { style: hint, children: t('page.auto_edit_hint') })
            ]
          })
        ]
      }),
      jsxs('label', {
        style: { alignItems: 'center', display: 'flex', fontSize: 12, gap: 8 },
        children: [
          jsx('span', { style: { minWidth: 180 }, children: t('page.inject') }),
          jsx('select', {
            onChange: event => void setSettings({ inject: event.target.value }),
            style: {
              background: 'var(--ui-bg-input)',
              border: '1px solid var(--ui-stroke-secondary)',
              borderRadius: 6,
              color: 'inherit',
              font: 'inherit',
              fontSize: 12,
              padding: '3px 6px'
            },
            value: settings.inject || 'auto',
            children: [
              jsx('option', { value: 'auto', children: t('page.inject_auto') }),
              jsx('option', { value: 'always', children: t('page.inject_always') }),
              jsx('option', { value: 'off', children: t('page.inject_off') })
            ]
          })
        ]
      }),
      ...[
        ['max_chars', t('page.budget'), 80, 2000, 20],
        ['max_notes_per_session', t('page.cap'), 1, 20, 1],
        ['history_depth', t('page.history'), 0, 50, 1]
      ].map(([key, label, min, max, step]) =>
        jsxs(
          'label',
          {
            style: { alignItems: 'center', display: 'flex', fontSize: 12, gap: 8 },
            children: [
              jsx('span', { style: { minWidth: 180 }, children: label }),
              jsx(Input, {
                max,
                min,
                onChange: event => num(key, event.target.value),
                step,
                style: { width: 90 },
                type: 'number',
                value: settings[key] ?? ''
              })
            ]
          },
          key
        )
      )
    ]
  })
}

function NotesPage() {
  useT()
  const data = useValue($data)
  const status = useValue($status)
  const [name, setName] = useState('')
  const [color, setColor] = useState('orange')
  const sid = useHostAtom(host.state.focusedStoredSessionId)

  useEffect(() => {
    if (!status.loaded) {
      void load()
    }
  }, [status.loaded])

  const create = () => {
    const clean = name.trim()
    if (!clean) {
      return
    }
    void createNote(clean, color, sid)
    setName('')
  }

  return jsx('div', {
    style: { height: '100%', overflowY: 'auto' },
    children: jsxs('div', {
      style: { display: 'flex', flexDirection: 'column', gap: 16, margin: '0 auto', maxWidth: 780, padding: '24px 20px' },
      children: [
        jsxs('div', {
          children: [
            jsx('h1', { style: { fontSize: 18, fontWeight: 600, margin: 0 }, children: t('page.title') }),
            jsx('p', { style: { ...hint, fontSize: 12, margin: '4px 0 0', maxWidth: 620 }, children: t('page.lead') })
          ]
        }),
        status.error ? jsx('div', { style: { ...hint, color: 'var(--ui-red)' }, children: status.error }) : null,
        data.pending.length
          ? jsxs('div', {
              style: { display: 'flex', flexDirection: 'column', gap: 8 },
              children: [
                jsx('div', { style: { fontSize: 12, fontWeight: 600 }, children: t('page.proposals') }),
                ...data.pending.map(entry => jsx(PendingCard, { entry }, entry.id))
              ]
            })
          : null,
        jsxs('div', {
          style: { alignItems: 'center', display: 'flex', gap: 8 },
          children: [
            jsx(ColorPicker, { color, label: t('note.color'), onChange: setColor }),
            jsx(Input, {
              'aria-label': t('page.name'),
              onChange: event => setName(event.target.value),
              onKeyDown: event => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                  create()
                }
              },
              placeholder: t('page.new'),
              style: { flex: 1, minWidth: 0 },
              value: name
            }),
            jsx(Button, { disabled: !name.trim(), onClick: create, size: 'sm', children: t('page.new') })
          ]
        }),
        jsx('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 }, children: [
          jsx('div', { style: { fontSize: 12, fontWeight: 600 }, children: t('page.all') }),
          data.notes.length
            ? data.notes.map(note => jsx(NoteCard, { note, sid: sid && note.sessions.includes(sid) ? sid : '' }, note.id))
            : jsx('div', { style: hint, children: t('page.empty') })
        ] }),
        jsx('div', {
          style: { borderTop: '1px solid var(--ui-stroke-secondary)', paddingTop: 12 },
          children: jsx(Settings, {})
        })
      ]
    })
  })
}

// ── status bar ───────────────────────────────────────────────────────────

function StatusChip() {
  useT()
  const data = useValue($data)
  const sid = useHostAtom(host.state.focusedStoredSessionId)
  const notes = notesOnSession(data, sid)
  if (!notes.length) {
    return null
  }

  return jsx(Button, {
    onClick: () => host.revealPane(PANE),
    size: 'xs',
    variant: 'ghost',
    children: [
      ...notes.slice(0, 3).map(note => jsx(Fragment, { children: dot(note.color, 6) }, note.id)),
      jsx('span', { style: { marginLeft: 4 }, children: notes.length })
    ]
  })
}

// ── register ─────────────────────────────────────────────────────────────

export default {
  id: ID,
  name: 'Sticky Tags',
  description: 'Notes that live on conversations: pin one note to many chats, rewrite it once.',
  register(ctx) {
    restCtx = ctx
    ctx.i18n.register(STRINGS)

    ctx.registerMany([
      {
        area: SESSION_ROW_AREAS.trailing,
        data: { render: ({ sessionId }) => jsx(RowDots, { sessionId }) },
        id: 'row-dots'
      },
      {
        area: PANES_AREA,
        title: 'Sticky notes',
        data: { placement: 'right', title: 'Sticky notes', width: '320px', tabTitleText: () => t('pane.title') },
        id: 'notes',
        render: () => jsx(NotesPane, {})
      },
      {
        area: COMPOSER_AREAS.top,
        id: 'composer-chips',
        render: () => jsx(ComposerChips, {})
      },
      { area: ROUTES_AREA, data: { path: PAGE }, id: 'page', render: () => jsx(NotesPage, {}) },
      { area: SIDEBAR_NAV_AREA, data: { codicon: 'note', label: 'Sticky notes', path: PAGE }, id: 'nav' },
      {
        area: STATUSBAR_AREAS.right,
        data: { render: () => jsx(StatusChip, {}) },
        id: 'status',
        order: 130
      },
      {
        area: PALETTE_AREA,
        data: {
          id: `${ID}.pane`,
          keywords: ['sticky', 'note', '付箋', 'メモ'],
          label: 'Sticky notes: open the panel',
          run: () => host.revealPane(PANE)
        },
        id: 'palette-pane'
      },
      {
        area: PALETTE_AREA,
        data: {
          id: `${ID}.page`,
          keywords: ['sticky', 'note', '付箋', 'メモ', 'settings'],
          label: 'Sticky notes: manage notes and rewriting',
          run: () => host.navigate(PAGE)
        },
        id: 'palette-page'
      }
    ])

    // One palette row per note: pin / unpin on the focused chat.
    let paletteOff = () => undefined
    let paletteKey = ''

    const syncPalette = data => {
      const key = data.notes.map(note => `${note.id}:${note.name}`).join('|')
      if (key === paletteKey) {
        return
      }
      paletteKey = key
      paletteOff()
      paletteOff = ctx.registerMany(
        data.notes.map(note => ({
          area: PALETTE_AREA,
          data: {
            id: `${ID}.toggle.${note.id}`,
            keywords: ['sticky', 'note', '付箋', note.name],
            label: `Sticky note 「${note.name}」: pin / unpin on this chat`,
            run: () => {
              const sid = focusedSession()
              if (!sid) {
                host.notify({ kind: 'info', message: 'Open a chat first' })
                return
              }
              const on = (noteById($data.get(), note.id)?.sessions || []).includes(sid)
              void (on ? detachNote(note.id, sid) : attachNote(note.id, sid)).then(() =>
                host.notify({ durationMs: 1800, kind: 'success', message: on ? t('toast.detached') : t('toast.pinned') })
              )
            }
          },
          id: `palette-${note.id}`
        }))
      )
    }

    ctx.onDispose($data.subscribe(syncPalette))
    ctx.onDispose(() => paletteOff())

    ctx.onDispose(host.state.focusedStoredSessionId.subscribe(sid => {
      noteFocus(sid)
      void load()
    }))
    ctx.onEvent(`plugin.${ID}.notes.changed`, event => {
      const at = event?.payload?.updated_at
      if ((!at || at !== lastWrite) && !pendingWrites) {
        void load()
      }
    })
    ctx.setInterval(() => {
      if (!pendingWrites) {
        void load()
      }
    }, 120_000)
    ctx.setInterval(() => void claimTick(), CLAIM_EVERY_MS)
    ctx.onDispose(() => {
      restCtx = null
    })

    void load()
  }
}
