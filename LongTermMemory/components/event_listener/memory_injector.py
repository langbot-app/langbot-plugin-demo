from __future__ import annotations

import logging

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy

logger = logging.getLogger(__name__)


class MemoryInjector(EventListener):
    """L1 profile injector.

    Injects user core profile into system prompt via PromptPreProcessing.
    L2 episodic memory is handled separately by KnowledgeEngine.retrieve().
    """

    def __init__(self):
        super().__init__()

        @self.handler(events.PromptPreProcessing)
        async def on_prompt_preprocess(event_ctx: context.EventContext):
            try:
                await self._inject_profile(event_ctx)
            except Exception:
                logger.exception("Failed to inject profile")

    async def _inject_profile(self, event_ctx: context.EventContext) -> None:
        store = self.plugin.memory_store
        session_name: str = event_ctx.event.session_name
        logger.info(
            "[LongTermMemory] memory injection started: query_id=%s session_name=%s",
            event_ctx.query_id,
            session_name,
        )
        api = QueryBasedAPIProxy(
            query_id=event_ctx.query_id,
            plugin_runtime_handler=self.plugin.plugin_runtime_handler,
        )

        kb = await store.get_kb_config()
        if not kb:
            logger.info(
                "[LongTermMemory] memory injection skipped: query_id=%s reason=no_kb_config",
                event_ctx.query_id,
            )
            return

        kb_id, config = kb
        pipeline_kbs = await api.list_pipeline_knowledge_bases()
        if not any(kb_entry.get("uuid") == kb_id for kb_entry in pipeline_kbs):
            logger.info(
                "[LongTermMemory] memory injection skipped: query_id=%s kb_id=%s reason=kb_not_in_pipeline",
                event_ctx.query_id,
                kb_id,
            )
            return

        isolation = config.get("isolation", "session")
        query_vars = await api.get_query_vars()
        bot_uuid = await api.get_bot_uuid()

        launcher_type, launcher_id = store.split_session_name(session_name)
        scope_key = store.get_session_key(bot_uuid, launcher_type, launcher_id)
        sender_id = str(query_vars.get("sender_id", "") or "")
        sender_name = str(query_vars.get("sender_name", "") or "")

        session_profile = await store.load_session_profile(scope_key)
        session_profile_block = store.format_profile_prompt(
            session_profile, "## Session Memory"
        )
        speaker_profile_block = ""
        if sender_id:
            speaker_profile = await store.load_speaker_profile(scope_key, sender_id)
            speaker_profile_block = store.format_profile_prompt(
                speaker_profile, "## Current Speaker Profile"
            )

        # Build injection parts
        blocks: list[str] = []
        if session_profile_block.strip():
            blocks.append(session_profile_block)
        if speaker_profile_block.strip():
            blocks.append(speaker_profile_block)

        # Inject current speaker identity so LLM knows who is talking
        if sender_name:
            blocks.append(f"## Current Speaker\n- Name: {sender_name}\n- ID: {sender_id}")
        elif sender_id:
            blocks.append(f"## Current Speaker\n- ID: {sender_id}")

        if not blocks:
            logger.info(
                "[LongTermMemory] memory injection skipped: query_id=%s scope_key=%s sender_id=%s reason=no_profile_blocks",
                event_ctx.query_id,
                scope_key,
                sender_id,
            )
            return

        injection = "# Long-term Memory\n\n" + "\n\n".join(blocks)
        logger.info(
            "[LongTermMemory] memory injection ready: query_id=%s kb_id=%s scope_key=%s sender_id=%s block_count=%s prompt_chars=%s",
            event_ctx.query_id,
            kb_id,
            scope_key,
            sender_id,
            len(blocks),
            len(injection),
        )

        event_ctx.event.default_prompt.append(
            Message(role="system", content=injection)
        )
