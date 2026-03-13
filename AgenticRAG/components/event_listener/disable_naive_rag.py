from __future__ import annotations

import logging

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context

logger = logging.getLogger(__name__)


class DisableNaiveRAG(EventListener):
    """Disable the pipeline's automatic pre-processing RAG retrieval.

    When AgenticRAG is installed, knowledge base retrieval should go through
    the agent's query_knowledge tool instead of the automatic pre-processing
    stage.  This listener clears ``_knowledge_base_uuids`` during
    PromptPreProcessing so the runner skips naive RAG entirely.

    Plugins that handle their own retrieval (e.g. LongTermMemory) should
    remove their KB from ``_knowledge_base_uuids`` independently before
    this listener runs, so there is no ordering dependency.
    """

    def __init__(self):
        super().__init__()

        @self.handler(events.PromptPreProcessing)
        async def on_prompt_preprocess(event_ctx: context.EventContext):
            query_vars = await event_ctx.get_query_vars()
            kb_uuids: list[str] = query_vars.get("_knowledge_base_uuids", [])
            if kb_uuids:
                await event_ctx.set_query_var("_knowledge_base_uuids", [])
                logger.info(
                    "[AgenticRAG] disabled naive RAG pre-processing: query_id=%s removed_kbs=%s",
                    event_ctx.query_id,
                    kb_uuids,
                )
