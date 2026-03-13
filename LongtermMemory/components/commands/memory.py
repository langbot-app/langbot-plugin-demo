from __future__ import annotations

import logging
from typing import AsyncGenerator, NamedTuple

from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.api.entities.builtin.command.context import (
    CommandReturn,
    ExecuteContext,
)
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy

logger = logging.getLogger(__name__)


class _RuntimeContext(NamedTuple):
    api: QueryBasedAPIProxy
    bot_uuid: str
    query_vars: dict
    session_key: str
    user_key: str
    kb_id: str | None
    isolation: str
    config: dict


class Memory(Command):

    @staticmethod
    async def _build_runtime_context(
        plugin,
        context: ExecuteContext,
    ) -> _RuntimeContext:
        store = plugin.memory_store
        api = QueryBasedAPIProxy(
            query_id=context.query_id,
            plugin_runtime_handler=plugin.plugin_runtime_handler,
        )
        bot_uuid = await api.get_bot_uuid()
        query_vars = await api.get_query_vars()
        session_key, user_key, kb_id, isolation, config = (
            await store.resolve_user_context(context.session, bot_uuid)
        )
        return _RuntimeContext(
            api=api,
            bot_uuid=bot_uuid,
            query_vars=query_vars,
            session_key=session_key,
            user_key=user_key,
            kb_id=kb_id,
            isolation=isolation,
            config=config,
        )

    @staticmethod
    async def _is_memory_kb_active(
        store,
        api: QueryBasedAPIProxy,
        kb_id: str | None,
    ) -> bool:
        if not kb_id:
            return False
        pipeline_kbs = await api.list_pipeline_knowledge_bases()
        return any(kb.get("uuid") == kb_id for kb in pipeline_kbs)

    def __init__(self):
        super().__init__()

        @self.subcommand(
            name="",
            help="Show memory overview",
            usage="!memory",
            aliases=[],
        )
        async def root(
            self: Memory,
            context: ExecuteContext,
        ) -> AsyncGenerator[CommandReturn, None]:
            store = self.plugin.memory_store
            ctx = await self._build_runtime_context(self.plugin, context)

            sender_id = str(ctx.query_vars.get("sender_id", "") or "")
            session_profile = await store.load_session_profile(ctx.session_key)
            speaker_profile = (
                await store.load_speaker_profile(ctx.session_key, sender_id)
                if sender_id
                else {}
            )
            kb_active = await self._is_memory_kb_active(store, ctx.api, ctx.kb_id)

            lines = [f"[Memory] mode: {ctx.isolation}"]
            lines.append(f"Session: {ctx.session_key}")
            lines.append(f"Key: {ctx.user_key}")
            lines.append(
                f"Current speaker: {ctx.query_vars.get('sender_name') or '-'} ({sender_id or '-'})"
            )

            if store.has_profile_data(session_profile):
                lines.append(
                    f"Session profile: name={session_profile.get('name', '-')}, "
                    f"{len(session_profile.get('traits', []))} traits, "
                    f"{len(session_profile.get('preferences', []))} prefs"
                )
            else:
                lines.append("Session profile: (empty)")

            if sender_id and store.has_profile_data(speaker_profile):
                lines.append(
                    f"Speaker profile: name={speaker_profile.get('name', '-')}, "
                    f"{len(speaker_profile.get('traits', []))} traits, "
                    f"{len(speaker_profile.get('preferences', []))} prefs"
                )
            elif sender_id:
                lines.append("Speaker profile: (empty)")

            if ctx.kb_id and kb_active:
                lines.append(f"L2 (Episodic): KB={ctx.kb_id[:12]}... active")
            elif ctx.kb_id:
                lines.append(f"L2 (Episodic): KB={ctx.kb_id[:12]}... configured but inactive in this pipeline")
            else:
                lines.append("L2 (Episodic): no KB configured")

            yield CommandReturn(text="\n".join(lines))

        @self.subcommand(
            name="profile",
            help="Show session and speaker profiles",
            usage="!memory profile",
            aliases=["p"],
        )
        async def profile_cmd(
            self: Memory,
            context: ExecuteContext,
        ) -> AsyncGenerator[CommandReturn, None]:
            store = self.plugin.memory_store
            ctx = await self._build_runtime_context(self.plugin, context)

            sender_id = str(ctx.query_vars.get("sender_id", "") or "")
            session_profile = await store.load_session_profile(ctx.session_key)

            lines = ["[Session Profile]"]
            lines.append(f"Name: {session_profile.get('name') or '(not set)'}")
            lines.append(
                f"Traits: {', '.join(session_profile.get('traits', [])) or '(none)'}"
            )
            lines.append(
                "Preferences: "
                f"{', '.join(session_profile.get('preferences', [])) or '(none)'}"
            )
            lines.append(f"Notes: {session_profile.get('notes') or '(none)'}")

            if sender_id:
                speaker_profile = await store.load_speaker_profile(ctx.session_key, sender_id)
                lines.append("")
                lines.append("[Current Speaker Profile]")
                lines.append(f"Name: {speaker_profile.get('name') or '(not set)'}")
                lines.append(
                    f"Traits: {', '.join(speaker_profile.get('traits', [])) or '(none)'}"
                )
                lines.append(
                    "Preferences: "
                    f"{', '.join(speaker_profile.get('preferences', [])) or '(none)'}"
                )
                lines.append(f"Notes: {speaker_profile.get('notes') or '(none)'}")

            yield CommandReturn(text="\n".join(lines))

        @self.subcommand(
            name="search",
            help="Search episodic memories",
            usage="!memory search <query>",
            aliases=["s"],
        )
        async def search_cmd(
            self: Memory,
            context: ExecuteContext,
        ) -> AsyncGenerator[CommandReturn, None]:
            store = self.plugin.memory_store
            ctx = await self._build_runtime_context(self.plugin, context)

            if not ctx.kb_id or not await self._is_memory_kb_active(store, ctx.api, ctx.kb_id):
                yield CommandReturn(
                    text="[Memory] Memory knowledge base is not configured for the current pipeline."
                )
                return

            embedding_model_uuid = ctx.config.get("embedding_model_uuid", "")

            if not context.crt_params:
                yield CommandReturn(text="Usage: !memory search <query>")
                return

            query = " ".join(context.crt_params)

            episodes = await store.search_episodes(
                collection_id=ctx.kb_id,
                embedding_model_uuid=embedding_model_uuid,
                query=query,
                user_key=ctx.user_key,
                top_k=10,
            )

            if not episodes:
                yield CommandReturn(text="[Memory] No episodes found.")
                return

            lines = [f"[Memory] Found {len(episodes)} episode(s):"]
            for ep in episodes:
                ts = ep["timestamp"][:10] if ep.get("timestamp") else "?"
                imp = ep.get("importance", 2)
                tags = ", ".join(ep.get("tags", []))
                tag_str = f" [{tags}]" if tags else ""
                lines.append(f"  {ts} (imp:{imp}){tag_str} {ep['content']}")

            yield CommandReturn(text="\n".join(lines))
