from __future__ import annotations

import logging

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy

logger = logging.getLogger(__name__)


class MemoryInjector(EventListener):
    """L1 profile + L2 episodic memory injector.

    During PromptPreProcessing:
    - L1 core profile is injected into the system prompt (default_prompt).
    - L2 episodic memory is retrieved from the memory KB and injected into
      the conversation context (prompt) so the LLM has automatic recall.
    - Memory KB is removed from ``_knowledge_base_uuids`` so the runner's
      naive RAG does not duplicate the retrieval.  The memory KB remains
      accessible via AgenticRAG's ``query_knowledge`` tool for deeper or
      filtered queries initiated by the LLM.
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

        # Remove memory KB from naive RAG pre-processing; L2 episodic
        # retrieval is handled below so it works regardless of whether
        # AgenticRAG is installed.
        query_vars = await api.get_query_vars()
        kb_uuids: list[str] = query_vars.get("_knowledge_base_uuids", [])
        if kb_id in kb_uuids:
            kb_uuids = [u for u in kb_uuids if u != kb_id]
            await api.set_query_var("_knowledge_base_uuids", kb_uuids)

        # --- L2 episodic memory retrieval ---
        user_message_text: str = query_vars.get("user_message_text", "")
        if user_message_text:
            try:
                entries = await api.retrieve_knowledge(
                    kb_id=kb_id,
                    query_text=user_message_text,
                    top_k=3,
                )
                if entries:
                    texts: list[str] = []
                    for i, entry in enumerate(entries, 1):
                        for content in entry.get("content", []):
                            if content.get("type") == "text" and content.get("text"):
                                texts.append(f"[{i}] {content['text']}")
                    if texts:
                        l2_block = "# Relevant Memories\n\n" + "\n\n".join(texts)
                        event_ctx.event.prompt.append(
                            Message(role="system", content=l2_block)
                        )
                        logger.info(
                            "[LongTermMemory] L2 episodic memory injected: query_id=%s kb_id=%s entry_count=%s",
                            event_ctx.query_id,
                            kb_id,
                            len(texts),
                        )
            except Exception:
                logger.exception(
                    "[LongTermMemory] L2 episodic retrieval failed: query_id=%s kb_id=%s",
                    event_ctx.query_id,
                    kb_id,
                )

        isolation = config.get("isolation", "session")
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
