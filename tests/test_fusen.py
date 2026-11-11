"""Tests for the fusen plugin. Stdlib only: ``python -m unittest discover -s tests``.

The plugin lives in a directory whose name is not a Python identifier, so it is
loaded as ``fusen`` from its directory — the same way Hermes imports it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if "fusen" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "fusen", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["fusen"] = _module
    _spec.loader.exec_module(_module)

from fusen import fusen_commands, fusen_inject, fusen_store, fusen_tools  # noqa: E402

commands, inject, store, tools = fusen_commands, fusen_inject, fusen_store, fusen_tools

SID_A = "20261105_113540_68ca42"
SID_B = "20261104_090000_aaa111"


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fusen-test-")
        fusen_store.set_data_dir(self.tmp)
        fusen_store.invalidate()
        fusen_inject._sent.clear()
        fusen_inject._dirty.clear()
        fusen_inject._carries.clear()

    def tearDown(self) -> None:
        fusen_store.set_data_dir(None)
        fusen_store.invalidate()

    # ── shape ────────────────────────────────────────────────────────────

    def test_empty_state_has_defaults(self) -> None:
        state = fusen_store.load()
        self.assertEqual(state["notes"], {})
        self.assertTrue(state["settings"]["auto_edit"])
        self.assertEqual(state["settings"]["inject"], "auto")
        self.assertEqual(state["settings"]["max_notes_per_session"], 5)

    def test_create_pins_and_renders(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="決済まわり", body="ここまで調査", pin_to=SID_A)
        fusen_store.write(state)

        self.assertTrue(note["id"].startswith("n"))
        state = fusen_store.load()
        self.assertEqual(len(fusen_store.notes_for(state, SID_A)), 1)
        text = fusen_store.render(state, SID_A)
        self.assertIn("<fusen-notes", text)
        self.assertIn("決済まわり", text)
        self.assertIn("ここまで調査", text)
        self.assertEqual(fusen_store.render(state, SID_B), "")

    def test_one_note_on_many_conversations_one_body(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="API仕様", pin_to=SID_A)
        fusen_store.attach(state, note["id"], SID_B)
        fusen_store.set_body(state, note["id"], "v2 に更新", author="user")
        fusen_store.write(state)

        state = fusen_store.load()
        for sid in (SID_A, SID_B):
            text = fusen_store.render(state, sid)
            self.assertIn("v2 に更新", text)
            self.assertIn('rev="2"', text)
        self.assertEqual(len(state["notes"][note["id"]]["sessions"]), 2)

    def test_several_notes_on_one_conversation_and_cap(self) -> None:
        state = fusen_store.load()
        for index in range(5):
            fusen_store.create(state, name=f"n{index}", pin_to=SID_A)
        fusen_store.write(state)
        with self.assertRaises(fusen_store.FusenError):
            fusen_store.create(state, name="overflow", pin_to=SID_A)

        state = fusen_store.load()
        self.assertEqual(len(fusen_store.notes_for(state, SID_A)), 5)
        text = fusen_store.render(state, SID_A)
        self.assertEqual(text.count("<note "), 5)

    def test_body_is_capped_and_control_characters_dropped(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="長文", body="a" * (fusen_store.MAX_BODY + 500) + "\x00\x07")
        self.assertEqual(len(note["body"]), fusen_store.MAX_BODY)
        self.assertNotIn("\x00", note["body"])

    def test_settings_are_clamped(self) -> None:
        state = fusen_store.load()
        fusen_store.set_settings(state, {"max_chars": 99999, "max_notes_per_session": 0, "inject": "nonsense"})
        self.assertEqual(state["settings"]["max_chars"], 2000)
        self.assertEqual(state["settings"]["max_notes_per_session"], 1)
        self.assertEqual(state["settings"]["inject"], "auto")

    # ── history ──────────────────────────────────────────────────────────

    def test_rewrite_keeps_history_and_revert(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="memo", body="最初")
        fusen_store.set_body(state, note["id"], "二番目")
        fusen_store.set_body(state, note["id"], "三番目", author="hermes")

        note = state["notes"][note["id"]]
        self.assertEqual(note["rev"], 3)
        self.assertEqual(note["author"], "hermes")
        self.assertEqual([entry["body"] for entry in note["history"]], ["最初", "二番目"])

        fusen_store.revert(state, note["id"])
        self.assertEqual(state["notes"][note["id"]]["body"], "二番目")
        self.assertEqual(state["notes"][note["id"]]["rev"], 4)

    def test_history_depth_is_enforced(self) -> None:
        state = fusen_store.load()
        fusen_store.set_settings(state, {"history_depth": 2})
        note = fusen_store.create(state, name="memo", body="0")
        for index in range(1, 6):
            fusen_store.set_body(state, note["id"], str(index))
        self.assertEqual(len(state["notes"][note["id"]]["history"]), 2)

    def test_expect_rev_refuses_a_stale_write(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="memo", body="mine")
        fusen_store.set_body(state, note["id"], "user edit")
        with self.assertRaises(fusen_store.FusenError):
            fusen_store.set_body(state, note["id"], "hermes edit", author="hermes", expect_rev=1)
        self.assertEqual(state["notes"][note["id"]]["body"], "user edit")

    # ── proposals ────────────────────────────────────────────────────────

    def test_proposal_waits_for_the_user(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="memo", body="before")
        entry = fusen_store.propose(state, note["id"], "after", reason="整理", sid=SID_A)

        self.assertEqual(state["notes"][note["id"]]["body"], "before")
        self.assertEqual(len(state["pending"]), 1)

        fusen_store.accept(state, entry["id"])
        self.assertEqual(state["notes"][note["id"]]["body"], "after")
        self.assertEqual(state["notes"][note["id"]]["author"], "hermes")
        self.assertEqual(state["pending"], [])

    def test_proposal_is_dropped_when_the_note_moved(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="memo", body="before")
        entry = fusen_store.propose(state, note["id"], "hermes text")
        fusen_store.set_body(state, note["id"], "user text")
        with self.assertRaises(fusen_store.FusenError):
            fusen_store.accept(state, entry["id"])
        self.assertEqual(state["notes"][note["id"]]["body"], "user text")

    def test_new_proposal_replaces_the_old_one(self) -> None:
        state = fusen_store.load()
        note = fusen_store.create(state, name="memo")
        fusen_store.propose(state, note["id"], "one")
        fusen_store.propose(state, note["id"], "two")
        self.assertEqual([entry["body"] for entry in state["pending"]], ["two"])

    # ── batch atomicity ──────────────────────────────────────────────────

    def test_a_bad_op_in_a_batch_writes_nothing(self) -> None:
        fusen_store.apply_ops([{"op": "create", "name": "ok"}])
        before = fusen_store.load()
        with self.assertRaises(fusen_store.FusenError):
            fusen_store.apply_ops([{"op": "create", "name": "half"}, {"op": "nonsense"}])
        after = fusen_store.load()
        self.assertEqual(after["notes"].keys(), before["notes"].keys())

    # ── cache ────────────────────────────────────────────────────────────

    def test_reads_are_cached_until_the_file_changes(self) -> None:
        fusen_store.apply_ops([{"op": "create", "name": "cached"}])
        first = fusen_store.load()
        second = fusen_store.load()
        self.assertIs(first, second)

        # Another writer replaces the file: the (mtime, size) key must notice.
        path = fusen_store.state_path()
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["notes"] = {}
        path.write_text(json.dumps(raw), encoding="utf-8")
        os.utime(path, (os.path.getmtime(path) + 2, os.path.getmtime(path) + 2))

        self.assertEqual(fusen_store.load()["notes"], {})

    def test_two_writers_do_not_lose_each_other(self) -> None:
        fusen_store.apply_ops([{"op": "create", "name": "a"}])
        # A second writer's change lands between our read and our write.
        fusen_store.apply_ops([{"op": "create", "name": "b"}])
        fusen_store.apply_ops([{"op": "create", "name": "c"}])
        self.assertEqual(len(fusen_store.load()["notes"]), 3)


class InjectCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fusen-inject-")
        fusen_store.set_data_dir(self.tmp)
        fusen_store.invalidate()
        fusen_inject._sent.clear()
        fusen_inject._dirty.clear()
        fusen_inject._carries.clear()
        state = fusen_store.load()
        self.note = fusen_store.create(state, name="memo", body="本文", pin_to=SID_A)
        fusen_store.write(state)
        self.state = fusen_store.load()

    def tearDown(self) -> None:
        fusen_store.set_data_dir(None)
        fusen_store.invalidate()

    def call(self, **kwargs):
        defaults = {"session_id": SID_A, "user_message": "hi", "conversation_history": [], "is_first_turn": False}
        defaults.update(kwargs)
        return fusen_inject.pre_llm_call(**defaults)

    def test_first_turn_injects(self) -> None:
        out = self.call(is_first_turn=True)
        self.assertIn("本文", out["context"])

    def test_second_turn_adds_nothing(self) -> None:
        self.assertIsNotNone(self.call(is_first_turn=True))
        self.assertIsNone(self.call(is_first_turn=False, conversation_history=[{"role": "user", "content": "<fusen-notes>"}]))

    def test_a_rewrite_re_injects(self) -> None:
        self.call(is_first_turn=True)
        fusen_store.apply_ops([{"op": "set_body", "note_id": self.note["id"], "body": "直した"}])
        out = self.call(is_first_turn=False, conversation_history=[{"role": "user", "content": "<fusen-notes>"}])
        self.assertIn("直した", out["context"])

    def test_marking_dirty_re_injects_without_a_signature_change(self) -> None:
        self.call(is_first_turn=True)
        fusen_inject.mark_dirty(SID_A)
        self.assertIsNotNone(self.call(is_first_turn=False, conversation_history=[{"role": "user", "content": "<fusen-notes>"}]))

    def test_a_fresh_process_does_not_repeat_a_block_already_in_history(self) -> None:
        history = [{"role": "user", "content": "…<fusen-notes note=\"x\">本文</fusen-notes>"}]
        self.assertIsNone(self.call(is_first_turn=False, conversation_history=history))

    def test_a_fresh_process_repairs_a_conversation_without_the_block(self) -> None:
        out = self.call(is_first_turn=False, conversation_history=[{"role": "user", "content": "古い会話"}])
        self.assertIsNotNone(out)

    def test_a_conversation_without_notes_is_never_touched(self) -> None:
        self.assertIsNone(self.call(session_id=SID_B, is_first_turn=True))

    def test_inject_off_silences_it(self) -> None:
        fusen_store.apply_ops([{"op": "settings", "patch": {"inject": "off"}}])
        self.assertIsNone(self.call(is_first_turn=True))

    def test_inject_always_every_turn(self) -> None:
        fusen_store.apply_ops([{"op": "settings", "patch": {"inject": "always"}}])
        self.assertIsNotNone(self.call(is_first_turn=True))
        self.assertIsNotNone(self.call(is_first_turn=False, conversation_history=[{"role": "user", "content": "<fusen-notes>"}]))

    def test_compaction_hook_marks_the_session_dirty(self) -> None:
        self.call(is_first_turn=True)
        fusen_inject.post_compaction(session_id=SID_A)
        self.assertIn(SID_A, fusen_inject._dirty)

    def test_delete_hook_unpins(self) -> None:
        fusen_inject.forget(SID_A)
        fusen_inject.on_session_delete(session_id=SID_A, reason="delete")
        self.assertEqual(fusen_store.load()["notes"][self.note["id"]]["sessions"], [])

    def test_archive_hook_keeps_the_pin(self) -> None:
        fusen_inject.on_session_delete(session_id=SID_A, reason="archive")
        self.assertEqual(fusen_store.load()["notes"][self.note["id"]]["sessions"], [SID_A])

    def test_an_unknown_session_is_harmless(self) -> None:
        fusen_inject.on_session_delete(session_id="nope", reason="delete")
        self.assertEqual(fusen_store.load()["notes"][self.note["id"]]["sessions"], [SID_A])


class ToolCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fusen-tools-")
        fusen_store.set_data_dir(self.tmp)
        fusen_store.invalidate()
        fusen_inject._sent.clear()
        state = fusen_store.load()
        self.note = fusen_store.create(state, name="調査メモ", body="途中まで", pin_to=SID_A)
        fusen_store.write(state)
        self.ctx = _FakeContext()
        fusen_tools.bind(self.ctx)

    def tearDown(self) -> None:
        fusen_store.set_data_dir(None)
        fusen_store.invalidate()
        fusen_tools.bind(None)

    def test_list_reports_the_pinned_notes(self) -> None:
        out = json.loads(fusen_tools.fusen_notes({"action": "list"}, session_id=SID_A))
        self.assertTrue(out["ok"])
        self.assertEqual(out["notes"][0]["name"], "調査メモ")
        self.assertTrue(out["auto_edit"])

    def test_search_finds_the_other_conversations(self) -> None:
        fusen_store.apply_ops([{"op": "attach", "note_id": self.note["id"], "session_id": SID_B}])
        out = json.loads(fusen_tools.fusen_notes({"action": "search", "note_id": self.note["id"]}, session_id=SID_A))
        self.assertEqual(sorted(out["session_ids"]), sorted([SID_A, SID_B]))

    def test_read_goes_through_dispatch_tool(self) -> None:
        out = json.loads(fusen_tools.fusen_notes({"action": "read", "session_id": SID_B}, session_id=SID_A))
        self.assertTrue(out["ok"])
        self.assertEqual(self.ctx.calls[-1][0], "session_search")
        self.assertEqual(self.ctx.calls[-1][1], {"session_id": SID_B})

    def test_write_applies_when_auto_edit_is_on(self) -> None:
        out = json.loads(
            fusen_tools.fusen_write(
                {"action": "write", "note_id": self.note["id"], "body": "更新した", "expect_rev": 1},
                session_id=SID_A,
            )
        )
        self.assertTrue(out["applied"])
        self.assertEqual(fusen_store.load()["notes"][self.note["id"]]["body"], "更新した")

    def test_write_becomes_a_proposal_when_off(self) -> None:
        fusen_store.apply_ops([{"op": "settings", "patch": {"auto_edit": False}}])
        out = json.loads(
            fusen_tools.fusen_write({"action": "write", "note_id": self.note["id"], "body": "案"}, session_id=SID_A)
        )
        self.assertTrue(out["proposed"])
        self.assertFalse(out["applied"])
        self.assertEqual(fusen_store.load()["notes"][self.note["id"]]["body"], "途中まで")
        self.assertEqual(len(fusen_store.load()["pending"]), 1)

    def test_pin_and_unpin(self) -> None:
        out = json.loads(fusen_tools.fusen_pin({"action": "attach", "note_id": self.note["id"]}, session_id=SID_B))
        self.assertTrue(out["ok"])
        self.assertEqual(out["pinned_here"], 1)
        out = json.loads(fusen_tools.fusen_pin({"action": "detach", "note_id": self.note["id"]}, session_id=SID_B))
        self.assertEqual(out["pinned_here"], 0)

    def test_an_unknown_note_is_an_error_not_a_crash(self) -> None:
        out = json.loads(fusen_tools.fusen_notes({"action": "get", "note_id": "nope"}, session_id=SID_A))
        self.assertFalse(out["ok"])


class CommandCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fusen-cmd-")
        fusen_store.set_data_dir(self.tmp)
        fusen_store.invalidate()
        fusen_inject._sent.clear()

    def tearDown(self) -> None:
        fusen_store.set_data_dir(None)
        fusen_store.invalidate()

    def test_fusen_creates_and_pins(self) -> None:
        out = fusen_commands.fusen_command("買い物", session_id=SID_A)
        self.assertIn("買い物", out)
        state = fusen_store.load()
        self.assertEqual(len(fusen_store.notes_for(state, SID_A)), 1)

    def test_fusen_without_args_lists(self) -> None:
        fusen_commands.fusen_command("買い物", session_id=SID_A)
        out = fusen_commands.fusen_command("", session_id=SID_A)
        self.assertIn("買い物", out)
        self.assertIn("付箋 1枚", out)

    def test_fusenedit_writes_the_body(self) -> None:
        fusen_commands.fusen_command("買い物", session_id=SID_A)
        out = fusen_commands.fusenedit_command("卵と牛乳", session_id=SID_A)
        self.assertIn("rev 2", out)
        state = fusen_store.load()
        note = fusen_store.notes_for(state, SID_A)[0]
        self.assertEqual(note["body"], "卵と牛乳")

    def test_unfusen_keeps_the_note(self) -> None:
        fusen_commands.fusen_command("買い物", session_id=SID_A)
        fusen_commands.unfusen_command("", session_id=SID_A)
        state = fusen_store.load()
        self.assertEqual(fusen_store.notes_for(state, SID_A), [])
        self.assertEqual(len(state["notes"]), 1)

    def test_commands_need_a_session(self) -> None:
        self.assertIn("会話", fusen_commands.fusen_command("x", session_id=""))


class RegisterCase(unittest.TestCase):
    """register() must declare exactly what plugin.yaml promises."""

    def test_register_wires_tools_hooks_and_commands(self) -> None:
        ctx = _FakeContext()
        sys.modules["fusen"].register(ctx)

        self.assertEqual(sorted(ctx.tools), ["fusen_notes", "fusen_pin", "fusen_write"])
        self.assertEqual(sorted(ctx.hooks), ["on_session_delete", "post_compaction", "pre_llm_call"])
        self.assertEqual(sorted(ctx.commands), ["fusen", "fusenedit", "fusenundo", "unfusen"])

        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        for name in ctx.tools:
            self.assertIn(f"  - {name}", manifest)
        for name in ctx.hooks:
            self.assertIn(f"  - {name}", manifest)

    def test_register_binds_the_dispatch_context(self) -> None:
        ctx = _FakeContext()
        sys.modules["fusen"].register(ctx)
        self.assertIs(fusen_tools._ctx, ctx)


class ApiCase(unittest.TestCase):
    """The desktop's routes, called the way FastAPI calls them."""

    _EVENTS_MODULE = "hermes_cli.plugin_events"

    @classmethod
    def setUpClass(cls) -> None:
        # The routes announce writes on the host's event bus. Outside a running host, importing
        # the bus pulls in the gateway, which can relaunch the interpreter. The tests swap in a
        # recorder: what they check is the REST answer, and that a write was announced.
        cls.events: list[tuple[str, str, dict]] = []
        recorder = types.ModuleType(cls._EVENTS_MODULE)
        recorder.broadcast_plugin_event = lambda plugin, event, payload=None: cls.events.append(
            (plugin, event, dict(payload or {}))
        )
        cls._saved_events_module = sys.modules.get(cls._EVENTS_MODULE)
        sys.modules[cls._EVENTS_MODULE] = recorder

        spec = importlib.util.spec_from_file_location("fusen_api", ROOT / "dashboard" / "plugin_api.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.api = module

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._saved_events_module is None:
            sys.modules.pop(cls._EVENTS_MODULE, None)
        else:
            sys.modules[cls._EVENTS_MODULE] = cls._saved_events_module

    def setUp(self) -> None:
        self.events.clear()
        self.tmp = tempfile.mkdtemp(prefix="fusen-api-")
        self.api.store.set_data_dir(self.tmp)
        self.api.store.invalidate()

    def tearDown(self) -> None:
        self.api.store.set_data_dir(None)
        self.api.store.invalidate()

    def test_state_then_ops_round_trip(self) -> None:
        self.assertEqual(self.api.get_state()["notes"], [])
        payload = self.api.post_ops({"ops": [{"op": "create", "name": "a", "pin_to": SID_A}], "session_id": SID_A})
        self.assertEqual(len(payload["notes"]), 1)
        self.assertEqual(payload["session_note_ids"], [payload["notes"][0]["id"]])
        self.assertEqual([(p, e) for p, e, _ in self.events], [("fusen", "notes.changed")])
        self.assertEqual(self.events[0][2]["session_id"], SID_A)

        note_id = payload["notes"][0]["id"]
        payload = self.api.post_ops({"ops": [{"op": "set_body", "note_id": note_id, "body": "x"}]})
        self.assertEqual(payload["notes"][0]["rev"], 2)

    def test_a_bad_session_id_is_a_400(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.api.get_state(session_id="../../etc/passwd")
        self.assertEqual(caught.exception.status_code, 400)

    def test_arm_rejects_an_unknown_note(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.api.arm({"note_id": "nmissing", "since": 1})
        self.assertEqual(caught.exception.status_code, 404)

    def test_arm_accepts_a_known_note(self) -> None:
        note_id = self.api.post_ops({"ops": [{"op": "create", "name": "a"}]})["notes"][0]["id"]
        out = self.api.arm({"note_id": note_id, "since": 1700000000})
        self.assertTrue(out["ok"])
        self.assertEqual(out["name"], "a")

    def test_settings_op_is_clamped_over_http(self) -> None:
        payload = self.api.post_ops({"ops": [{"op": "settings", "patch": {"max_chars": 999999}}]})
        self.assertEqual(payload["settings"]["max_chars"], 2000)

    def test_each_hermes_home_reads_its_own_file(self) -> None:
        """A second profile must never see the launch profile's notes.

        The host binds ``?profile=`` into the request's home scope, which is what
        ``get_hermes_home()`` reads. ``HERMES_HOME`` is the same seam's other source, so this
        drives the real resolution without needing the host: write in A, read in B, read A again.
        """
        self.api.store.set_data_dir(None)
        home_a = tempfile.mkdtemp(prefix="fusen-home-a-")
        home_b = tempfile.mkdtemp(prefix="fusen-home-b-")
        saved = os.environ.get("HERMES_HOME")
        try:
            os.environ["HERMES_HOME"] = home_a
            self.api.post_ops({"ops": [{"op": "create", "name": "only-a"}]})
            os.environ["HERMES_HOME"] = home_b
            self.assertEqual(self.api.get_state()["notes"], [])
            os.environ["HERMES_HOME"] = home_a
            self.assertEqual([note["name"] for note in self.api.get_state()["notes"]], ["only-a"])
        finally:
            if saved is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = saved

    def test_the_router_mounts(self) -> None:
        paths = {route.path for route in self.api.router.routes}
        self.assertEqual(paths, {"/state", "/ops", "/arm"})


class _FakeContext:
    """Minimal stand-in for the parts of PluginContext the plugin touches."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.tools: dict[str, dict] = {}
        self.hooks: dict[str, object] = {}
        self.commands: dict[str, object] = {}

    def dispatch_tool(self, name: str, args: dict, **_: object) -> str:
        self.calls.append((name, args))
        return json.dumps({"ok": True, "messages": []})

    def register_tool(self, name: str, toolset: str, schema: dict, handler: object, **_: object) -> None:
        assert schema["name"] == name, "schema name must match the registered name"
        self.tools[name] = {"handler": handler, "toolset": toolset}

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks[name] = callback

    def register_command(self, name: str, handler: object, **_: object) -> None:
        self.commands[name] = handler


if __name__ == "__main__":
    unittest.main()
