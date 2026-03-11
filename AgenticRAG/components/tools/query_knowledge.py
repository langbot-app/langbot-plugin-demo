from __future__ import annotations

import json
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy


class QueryKnowledge(Tool):

    async def call(self, params: dict[str, Any], session: provider_session.Session, query_id: int) -> str:
        api = QueryBasedAPIProxy(
            query_id=query_id,
            plugin_runtime_handler=self.plugin.plugin_runtime_handler,
        )

        action = params.get("action", "list")

        if action == "list":
            knowledge_bases = await api.list_pipeline_knowledge_bases()
            if not knowledge_bases:
                return "No knowledge bases are configured for the current pipeline."
            return json.dumps(knowledge_bases, ensure_ascii=False)

        elif action == "query":
            kb_id = params.get("kb_id")
            query_text = params.get("query_text")
            if not kb_id or not query_text:
                return "Both kb_id and query_text are required for action 'query'."

            if not isinstance(kb_id, str):
                return "kb_id must be a string."

            if not isinstance(query_text, str) or not query_text.strip():
                return "query_text must be a non-empty string."

            top_k = params.get("top_k", 5)
            if not isinstance(top_k, int) or top_k <= 0:
                return "top_k must be a positive integer."

            knowledge_bases = await api.list_pipeline_knowledge_bases()
            allowed_kb_ids = {
                kb.get("uuid")
                for kb in knowledge_bases
                if isinstance(kb, dict) and kb.get("uuid")
            }
            if kb_id not in allowed_kb_ids:
                return f"Knowledge base {kb_id} is not configured for the current pipeline."

            # Keep the agent-facing tool surface minimal here. Although the
            # underlying runtime supports metadata filters, different knowledge
            # engines do not expose a consistent, query-time filter schema to
            # the agent, so passing raw filters would be unreliable.
            results = await api.retrieve_knowledge(
                kb_id=kb_id,
                query_text=query_text.strip(),
                top_k=top_k,
            )
            if not results:
                return "No relevant documents found."
            return json.dumps(results, ensure_ascii=False)

        else:
            return f"Unknown action: {action}. Use 'list' or 'query'."
