from __future__ import annotations

import copy
import json
import time
import uuid
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _default_profile() -> dict[str, Any]:
    return {
        "name": "",
        "traits": [],
        "preferences": [],
        "notes": "",
        "updated_at": "",
    }


class MemoryStore:
    """Dual-layer memory store.

    L1 (Core Profile): Binary Storage (JSON) - read/write via plugin storage API.
    L2 (Episodic Memory): vector DB - read/write via plugin vector API.
    """

    _PROFILE_FIELDS = ("name", "traits", "preferences", "notes")
    _MAX_PROFILE_CACHE_SIZE = 256
    _MAX_NOTES_LENGTH = 2000

    def __init__(
        self,
        plugin: Any,
        max_profile_traits: int = 20,
        max_profile_preferences: int = 10,
    ):
        self.plugin = plugin
        self.max_profile_traits = max_profile_traits
        self.max_profile_preferences = max_profile_preferences
        self._kb_config_cache: dict[str, dict[str, Any]] | None = None
        # L1 profile cache: user_key -> (monotonic_timestamp, profile_dict)
        self._profile_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._PROFILE_CACHE_TTL = 30  # seconds

    # ======================== common helpers ========================

    @staticmethod
    def has_profile_data(profile: dict[str, Any]) -> bool:
        return any(
            profile.get(f) for f in ("name", "traits", "preferences", "notes")
        )

    @staticmethod
    def format_profile_text(profile: dict[str, Any]) -> str:
        """Compact profile text for tool return values."""
        parts = []
        if profile.get("name"):
            parts.append(f"Name: {profile['name']}")
        if profile.get("traits"):
            parts.append(f"Traits: {', '.join(profile['traits'])}")
        if profile.get("preferences"):
            parts.append(f"Preferences: {', '.join(profile['preferences'])}")
        if profile.get("notes"):
            parts.append(f"Notes: {profile['notes']}")
        return "\n".join(parts)

    # ======================== key helpers ========================

    @staticmethod
    def get_session_key(
        bot_uuid: str,
        launcher_type_value: str,
        launcher_id: Any,
    ) -> str:
        session_id = f"{launcher_type_value}_{launcher_id}"
        if not bot_uuid:
            return session_id
        return f"{bot_uuid}:{session_id}"

    @staticmethod
    def get_user_key(session_key: str, isolation: str, bot_uuid: str = "") -> str:
        if isolation == "session":
            return session_key
        if bot_uuid:
            return f"bot:{bot_uuid}"
        return "global"

    @classmethod
    def get_scope_key(
        cls,
        bot_uuid: str,
        launcher_type_value: str,
        launcher_id: Any,
        isolation: str,
    ) -> str:
        session_key = cls.get_session_key(bot_uuid, launcher_type_value, launcher_id)
        return cls.get_user_key(session_key, isolation, bot_uuid)

    @staticmethod
    def split_session_name(session_name: str) -> tuple[str, str]:
        launcher_type, sep, launcher_id = session_name.partition("_")
        if not sep:
            return session_name, ""
        return launcher_type, launcher_id

    @classmethod
    def get_scope_key_from_session_name(
        cls,
        bot_uuid: str,
        session_name: str,
        isolation: str,
    ) -> str:
        launcher_type, launcher_id = cls.split_session_name(session_name)
        return cls.get_scope_key(bot_uuid, launcher_type, launcher_id, isolation)

    async def resolve_user_context(
        self, session: Any, bot_uuid: str = ""
    ) -> tuple[str, str, str | None, str, dict[str, Any]]:
        """Derive session_key, user_key, kb_id, isolation from a session.

        Returns (session_key, user_key, kb_id_or_None, isolation, kb_config).
        kb_id is None and kb_config is {} when no KB is configured.
        """
        kb_id, config = None, {}
        kb = await self.get_kb_config()
        if kb:
            kb_id, config = kb
        isolation = config.get("isolation", "session")
        session_key = self.get_session_key(
            bot_uuid, session.launcher_type.value, session.launcher_id
        )
        user_key = self.get_user_key(session_key, isolation, bot_uuid)
        return session_key, user_key, kb_id, isolation, config

    async def resolve_user_key(self, session: Any, bot_uuid: str = "") -> str:
        """Derive user_key from a session object (lightweight, no kb_id/config)."""
        kb = await self.get_kb_config()
        isolation = kb[1].get("isolation", "session") if kb else "session"
        session_key = self.get_session_key(
            bot_uuid, session.launcher_type.value, session.launcher_id
        )
        return self.get_user_key(session_key, isolation, bot_uuid)

    # ======================== KB config persistence ========================

    _KB_CONFIGS_KEY = "kb_configs"

    async def save_kb_config(self, kb_id: str, config: dict[str, Any]) -> None:
        configs = await self._read_json(self._KB_CONFIGS_KEY) or {}
        configs[kb_id] = config
        await self._write_json(self._KB_CONFIGS_KEY, configs)
        self._kb_config_cache = configs

    async def remove_kb_config(self, kb_id: str) -> None:
        configs = await self._read_json(self._KB_CONFIGS_KEY) or {}
        configs.pop(kb_id, None)
        await self._write_json(self._KB_CONFIGS_KEY, configs)
        self._kb_config_cache = configs

    async def get_kb_configs(self) -> dict[str, dict[str, Any]]:
        if self._kb_config_cache is not None:
            return self._kb_config_cache
        self._kb_config_cache = await self._read_json(self._KB_CONFIGS_KEY) or {}
        return self._kb_config_cache

    async def get_kb_config(self) -> tuple[str, dict[str, Any]] | None:
        """Return (kb_id, config) for the single registered KB, or None."""
        configs = await self.get_kb_configs()
        if configs:
            kb_id = next(iter(configs))
            return kb_id, configs[kb_id]
        return None

    # ======================== L1: profile (Binary Storage) ========================

    def _session_profile_key(self, scope_key: str) -> str:
        return f"ps:{scope_key}"

    def _speaker_profile_key(self, scope_key: str, sender_id: str) -> str:
        return f"pp:{scope_key}:{sender_id}"

    async def _read_json(self, key: str) -> Any:
        try:
            data = await self.plugin.get_plugin_storage(key)
        except Exception:
            logger.debug("storage key %s not found", key)
            return None
        if not data:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("storage key %s has corrupted data: %s", key, e)
            return None

    async def _write_json(self, key: str, obj: Any) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        await self.plugin.set_plugin_storage(key, data)

    async def _load_profile_by_storage_key(self, storage_key: str) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._profile_cache.get(storage_key)
        if cached and now - cached[0] < self._PROFILE_CACHE_TTL:
            return cached[1]

        profile = await self._read_json(storage_key)
        profile = profile if profile else _default_profile()
        if len(self._profile_cache) >= self._MAX_PROFILE_CACHE_SIZE:
            self._profile_cache.clear()
        self._profile_cache[storage_key] = (now, profile)
        return profile

    async def _save_profile_by_storage_key(
        self, storage_key: str, profile: dict[str, Any]
    ) -> None:
        profile["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self._write_json(storage_key, profile)
        if len(self._profile_cache) >= self._MAX_PROFILE_CACHE_SIZE:
            self._profile_cache.clear()
        self._profile_cache[storage_key] = (time.monotonic(), profile)

    async def load_session_profile(self, scope_key: str) -> dict[str, Any]:
        return await self._load_profile_by_storage_key(
            self._session_profile_key(scope_key)
        )

    async def load_speaker_profile(
        self, scope_key: str, sender_id: str
    ) -> dict[str, Any]:
        if not sender_id:
            return _default_profile()
        return await self._load_profile_by_storage_key(
            self._speaker_profile_key(scope_key, sender_id)
        )

    async def _update_profile_field_by_storage_key(
        self,
        storage_key: str,
        field: str,
        action: str,
        value: str,
    ) -> dict[str, Any]:
        profile = copy.deepcopy(
            await self._load_profile_by_storage_key(storage_key)
        )

        if field == "name":
            profile["name"] = value
        elif field in ("traits", "preferences"):
            items: list[str] = profile.get(field, [])
            if action == "add":
                if value not in items:
                    items.append(value)
                    max_len = self.max_profile_traits if field == "traits" else self.max_profile_preferences
                    items = items[-max_len:]
                profile[field] = items
            elif action == "remove":
                profile[field] = [i for i in items if i != value]
            elif action == "set":
                profile[field] = [value]
        elif field == "notes":
            if action == "set":
                profile["notes"] = value[:self._MAX_NOTES_LENGTH]
            elif action == "add":
                existing = profile.get("notes", "")
                new_notes = f"{existing}; {value}" if existing else value
                if len(new_notes) > self._MAX_NOTES_LENGTH:
                    new_notes = new_notes[:self._MAX_NOTES_LENGTH]
                    logger.warning(
                        "notes for %s truncated to %d chars",
                        storage_key, self._MAX_NOTES_LENGTH,
                    )
                profile["notes"] = new_notes
            elif action == "remove":
                profile["notes"] = ""

        await self._save_profile_by_storage_key(storage_key, profile)
        return profile

    async def update_session_profile_field(
        self,
        scope_key: str,
        field: str,
        action: str,
        value: str,
    ) -> dict[str, Any]:
        return await self._update_profile_field_by_storage_key(
            self._session_profile_key(scope_key),
            field,
            action,
            value,
        )

    async def update_speaker_profile_field(
        self,
        scope_key: str,
        sender_id: str,
        field: str,
        action: str,
        value: str,
    ) -> dict[str, Any]:
        return await self._update_profile_field_by_storage_key(
            self._speaker_profile_key(scope_key, sender_id),
            field,
            action,
            value,
        )

    async def clear_session_profile(self, scope_key: str) -> None:
        await self._save_profile_by_storage_key(
            self._session_profile_key(scope_key), _default_profile()
        )

    async def clear_speaker_profile(self, scope_key: str, sender_id: str) -> None:
        await self._save_profile_by_storage_key(
            self._speaker_profile_key(scope_key, sender_id), _default_profile()
        )

    # ======================== L2: episodes (ChromaDB vector) ========================

    async def add_episode(
        self,
        collection_id: str,
        embedding_model_uuid: str,
        user_key: str,
        content: str,
        tags: list[str] | None = None,
        importance: int = 2,
        source: str = "agent",
        sender_id: str = "",
        sender_name: str = "",
        bot_uuid: str = "",
    ) -> dict[str, Any]:
        """Store an episodic memory into vector DB."""
        episode_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        importance = max(1, min(5, importance))
        tags = tags or []

        metadata = {
            "content": content,
            "tags": ",".join(tags),
            "importance": str(importance),
            "timestamp": timestamp,
            "user_key": user_key,
            "source": source,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "bot_uuid": bot_uuid,
        }

        vectors = await self.plugin.invoke_embedding(embedding_model_uuid, [content])

        await self.plugin.vector_upsert(
            collection_id=collection_id,
            vectors=vectors,
            ids=[episode_id],
            metadata=[metadata],
            documents=[content],
        )

        return {
            "id": episode_id,
            "content": content,
            "tags": tags,
            "importance": importance,
            "timestamp": timestamp,
        }

    async def search_episodes(
        self,
        collection_id: str,
        embedding_model_uuid: str,
        query: str,
        user_key: str | None = None,
        top_k: int = 5,
        sender_id: str = "",
        sender_name: str = "",
        time_after: str = "",
        time_before: str = "",
        importance_min: int | None = None,
        source: str = "",
    ) -> list[dict[str, Any]]:
        """Search episodic memories via vector similarity."""
        if not query.strip():
            return []

        vectors = await self.plugin.invoke_embedding(embedding_model_uuid, [query])
        query_vector = vectors[0]

        filters = {}
        if user_key:
            filters["user_key"] = user_key
        if sender_id:
            filters["sender_id"] = sender_id
        if sender_name:
            filters["sender_name"] = sender_name
        if source:
            filters["source"] = source
        if time_after or time_before:
            time_filter: dict[str, str] = {}
            if time_after:
                time_filter["$gte"] = time_after
            if time_before:
                time_filter["$lte"] = time_before
            filters["timestamp"] = time_filter
        if importance_min is not None:
            # importance is stored as a string ("1"-"5") in vector DB metadata;
            # string comparison works correctly for single-digit values in this range.
            filters["importance"] = {"$gte": str(importance_min)}

        results = await self.plugin.vector_search(
            collection_id=collection_id,
            query_vector=query_vector,
            top_k=top_k,
            filters=filters if filters else None,
        )

        episodes = []
        for r in results:
            meta = r.get("metadata", {})
            episodes.append({
                "id": r.get("id", ""),
                "content": meta.get("content", ""),
                "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                "importance": int(meta.get("importance", "2")),
                "timestamp": meta.get("timestamp", ""),
                "sender_id": meta.get("sender_id", ""),
                "sender_name": meta.get("sender_name", ""),
                "source": meta.get("source", ""),
                "score": r.get("score"),
            })
        return episodes

    async def delete_episodes_by_user(
        self, collection_id: str, user_key: str
    ) -> int:
        """Delete all episodes for a user_key."""
        return await self.plugin.vector_delete(
            collection_id=collection_id,
            filters={"user_key": user_key},
        )

    # ======================== formatting ========================

    @staticmethod
    def format_profile_prompt(
        profile: dict[str, Any],
        title: str = "## Memory (Profile)",
    ) -> str:
        if not MemoryStore.has_profile_data(profile):
            return ""

        parts: list[str] = []
        parts.append(title)

        if profile.get("name"):
            parts.append(f"- Name: {profile['name']}")
        if profile.get("traits"):
            parts.append(f"- Traits: {', '.join(profile['traits'])}")
        if profile.get("preferences"):
            parts.append(f"- Preferences: {', '.join(profile['preferences'])}")
        if profile.get("notes"):
            parts.append(f"- Notes: {profile['notes']}")
        if profile.get("updated_at"):
            parts.append(f"- Last updated: {profile['updated_at']}")

        return "\n".join(parts)
