from __future__ import annotations

import logging

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.entities.builtin.provider.message import Message

logger = logging.getLogger(__name__)

RAG_PRIORITY_SYSTEM_PROMPT = """# Knowledge Retrieval Policy

For questions involving facts, policies, rules, procedures, product behavior, configuration, or other domain-specific information, prefer calling the `query_knowledge` tool before answering.

Treat the configured knowledge bases as the primary source of truth for this conversation. Your own pretrained knowledge may be outdated or incomplete for in-scope topics.

Rules:
- If the answer depends on knowledge-base content, call `query_knowledge` instead of relying on memory.
- If you are unsure whether your answer is fully accurate, call `query_knowledge`.
- Start by listing available knowledge bases, then query the most relevant one or ones with a focused query.
- If retrieval is insufficient, refine the query and try again rather than guessing.

No automatic knowledge-base retrieval will happen unless you call `query_knowledge`."""


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
                event_ctx.event.default_prompt.append(
                    Message(role="system", content=RAG_PRIORITY_SYSTEM_PROMPT)
                )
                logger.info(
                    "[AgenticRAG] disabled naive RAG pre-processing and injected RAG-priority system prompt: query_id=%s removed_kbs=%s",
                    event_ctx.query_id,
                    kb_uuids,
                )
