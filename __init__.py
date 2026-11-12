"""fusen — a tag that carries a body, shared by every conversation it is pinned to.

Three halves, one store:

  * the agent turn — ``inject.pre_llm_call`` puts the pinned notes in front of
    the model, on the turns where its view is actually stale (see
    ``fusen_inject.py``);
  * the agent's hands — three tools plus the ``/fusen`` family of commands (the user
    settles proposals there; the tools cannot);
  * the desktop — ``desktop/plugin.js`` over the routes in
    ``dashboard/plugin_api.py``.

Nothing here patches Hermes core; every seam is a documented plugin API.
"""

from __future__ import annotations

import logging
from typing import Any

from . import fusen_commands as commands
from . import fusen_inject as inject
from . import fusen_i18n as i18n
from . import fusen_store as store
from . import fusen_tools as tools

log = logging.getLogger(__name__)

__version__ = "1.1.0"


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

    # English is the default; fusen_i18n swaps in Japanese when Hermes itself is Japanese.
    for name, handler, key in (
        ("fusen", commands.fusen_command, "cmd.fusen"),
        ("unfusen", commands.unfusen_command, "cmd.unfusen"),
        ("fusenedit", commands.fusenedit_command, "cmd.fusenedit"),
        ("fusenundo", commands.fusenundo_command, "cmd.fusenundo"),
        ("fusenapply", commands.fusenapply_command, "cmd.fusenapply"),
        ("fusendismiss", commands.fusendismiss_command, "cmd.fusendismiss"),
    ):
        ctx.register_command(
            name,
            handler,
            description=i18n.msg(key),
            args_hint=i18n.msg(f"{key}.hint"),
        )

    log.debug("fusen registered (store: %s)", store.state_path())
