"""fusen — a tag that carries a body, shared by every conversation it is pinned to.

Three halves, one store:

  * the agent turn — ``inject.pre_llm_call`` puts the pinned notes in front of
    the model, on the turns where its view is actually stale (see
    ``fusen_inject.py``);
  * the agent's hands — three tools plus ``/fusen`` family commands;
  * the desktop — ``desktop/plugin.js`` over the routes in
    ``dashboard/plugin_api.py``.

Nothing here patches Hermes core; every seam is a documented plugin API.
"""

from __future__ import annotations

import logging
from typing import Any

from . import fusen_commands as commands
from . import fusen_inject as inject
from . import fusen_store as store
from . import fusen_tools as tools

log = logging.getLogger(__name__)

__version__ = "0.1.0"


def register(ctx: Any) -> None:
    tools.bind(ctx)

    ctx.register_tool(
        name="fusen_notes",
        toolset="fusen",
        schema=tools.SCHEMA_NOTES,
        handler=tools.fusen_notes,
    )
    ctx.register_tool(
        name="fusen_pin",
        toolset="fusen",
        schema=tools.SCHEMA_PIN,
        handler=tools.fusen_pin,
    )
    ctx.register_tool(
        name="fusen_write",
        toolset="fusen",
        schema=tools.SCHEMA_WRITE,
        handler=tools.fusen_write,
    )

    ctx.register_hook("pre_llm_call", inject.pre_llm_call)
    ctx.register_hook("post_compaction", inject.post_compaction)
    ctx.register_hook("on_session_delete", inject.on_session_delete)

    ctx.register_command(
        "fusen",
        commands.fusen_command,
        description="付箋を貼る・一覧する（名前なしでこの会話の付箋）",
        args_hint="付箋の名前",
    )
    ctx.register_command(
        "unfusen",
        commands.unfusen_command,
        description="この会話から付箋を外す（付箋そのものは残ります）",
        args_hint="付箋の名前かid",
    )
    ctx.register_command(
        "fusenedit",
        commands.fusenedit_command,
        description="付箋の本文を書き換える（全部の会話に反映）",
        args_hint="本文",
    )
    ctx.register_command(
        "fusenundo",
        commands.fusenundo_command,
        description="付箋をひとつ前の版に戻す",
        args_hint="付箋の名前かid",
    )

    log.debug("fusen registered (store: %s)", store.state_path())
