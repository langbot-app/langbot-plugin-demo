from __future__ import annotations

import logging
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy

logger = logging.getLogger(__name__)


class Forget(Tool):
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        store = self.plugin.memory_store
        api = QueryBasedAPIProxy(
            query_id=query_id,
            plugin_runtime_handler=self.plugin.plugin_runtime_handler,
        )
        bot_uuid = await api.get_bot_uuid()
        _, user_key, kb_id, _, config = await store.resolve_user_context(
            session, bot_uuid
        )

        if not kb_id:
            return "Error: no memory knowledge base configured."

        episode_id = params.get("episode_id", "")
        if not episode_id:
            return "Error: episode_id is required."

        logger.info(
            "[LongTermMemory] forget called: query_id=%s kb_id=%s user_key=%s episode_id=%s",
            query_id,
            kb_id,
            user_key,
            episode_id,
        )

        await store.delete_episode_by_id(
            collection_id=kb_id,
            episode_id=episode_id,
            user_key=user_key,
        )

        return f"Deleted episode {episode_id}."
