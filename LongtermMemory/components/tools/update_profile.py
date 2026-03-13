from __future__ import annotations

import logging
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy

logger = logging.getLogger(__name__)


class UpdateProfile(Tool):

    @staticmethod
    def _normalize_scope(scope: Any) -> str:
        if scope is None or scope == "":
            return ""
        if not isinstance(scope, str):
            return "__invalid__"
        scope = scope.strip().lower()
        if scope in ("session", "speaker"):
            return scope
        return "__invalid__"

    @staticmethod
    def _infer_scope(field: str, explicit_scope: str) -> str:
        if explicit_scope:
            return explicit_scope
        # Default to speaker-scoped profiles for stable person facts,
        # and session-scoped notes for shared conversational context.
        if field in ("name", "traits", "preferences"):
            return "speaker"
        return "session"

    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        store = self.plugin.memory_store

        field = params.get("field", "")
        action = params.get("action", "")
        value = params.get("value", "")
        scope = self._normalize_scope(params.get("scope", ""))

        if not all([field, action, value]):
            return "Error: field, action, and value are all required."

        if field not in ("name", "traits", "preferences", "notes"):
            return f"Error: invalid field '{field}'."

        if action not in ("set", "add", "remove"):
            return f"Error: invalid action '{action}'."

        if scope == "__invalid__":
            return "Error: invalid scope. Use 'session' or 'speaker'."

        api = QueryBasedAPIProxy(
            query_id=query_id,
            plugin_runtime_handler=self.plugin.plugin_runtime_handler,
        )
        bot_uuid = await api.get_bot_uuid()
        query_vars = await api.get_query_vars()
        sender_id = str(query_vars.get("sender_id", "") or "")

        session_key, _user_key, kb_id, _isolation, _ = await store.resolve_user_context(
            session, bot_uuid
        )
        if not kb_id:
            return "Error: no memory knowledge base configured. Create one first."

        pipeline_kbs = await api.list_pipeline_knowledge_bases()
        if not any(kb.get("uuid") == kb_id for kb in pipeline_kbs):
            return "Error: memory knowledge base is not configured for the current pipeline."

        target_scope = self._infer_scope(field, scope)

        if target_scope == "speaker":
            if not sender_id:
                return "Error: current speaker is unavailable."
            profile = await store.update_speaker_profile_field(
                scope_key=session_key,
                sender_id=sender_id,
                field=field,
                action=action,
                value=value,
            )
        else:
            profile = await store.update_session_profile_field(
                scope_key=session_key,
                field=field,
                action=action,
                value=value,
            )

        logger.info(
            "Updated %s profile %s.%s (%s) for %s",
            target_scope,
            field,
            action,
            value[:40],
            session_key,
        )

        return (
            f"{target_scope.capitalize()} profile updated.\n"
            + store.format_profile_text(profile)
        )
