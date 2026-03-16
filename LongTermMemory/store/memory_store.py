from __future__ import annotations

import copy
import json
import time
import uuid
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _default_profile() -> dict[str, Any]:
    return {
        "name": "",
        "traits": [],
        "preferences": [],
        "notes": "",
        "updated_at": "",
        "profile_slots": {
            "traits": {},
            "preferences": {},
        },
        "freeform_traits": [],
        "freeform_preferences": [],
    }


class MemoryStore:
    """Dual-layer memory store.

    L1 (Core Profile): Binary Storage (JSON) - read/write via plugin storage API.
    L2 (Episodic Memory): vector DB - read/write via plugin vector API.
    """

    _PROFILE_FIELDS = ("name", "traits", "preferences", "notes")
    _STRUCTURED_FIELDS = ("traits", "preferences")
    _MAX_PROFILE_CACHE_SIZE = 256
    _MAX_NOTES_LENGTH = 2000
    _MAX_SLOT_HISTORY = 8
    _RECENT_SLOT_CHANGE_DAYS = 30

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
        # L1 profile cache: storage_key -> (monotonic_timestamp, profile_dict)
        self._profile_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._PROFILE_CACHE_TTL = 30  # seconds

    @staticmethod
    def _preview_text(value: str, max_len: int = 120) -> str:
        text = value.strip().replace("\n", " ")
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

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
        for hint in MemoryStore._format_recent_slot_change_hints(profile, max_items=2):
            parts.append(hint)
        if profile.get("notes"):
            parts.append(f"Notes: {profile['notes']}")
        return "\n".join(parts)

    @staticmethod
    def _now_timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def normalize_timestamp(value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("timestamp cannot be empty")

        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"invalid timestamp '{text}'. Use ISO-8601 such as 2026-03-14T00:00:00Z"
            ) from exc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def normalize_optional_timestamp(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""
        return cls.normalize_timestamp(text)

    @staticmethod
    def _normalize_slot_key(value: str) -> str:
        return "_".join(str(value).strip().lower().split())

    @staticmethod
    def _normalize_text_list(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @classmethod
    def _normalize_slot_group(cls, raw_group: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(raw_group, dict):
            return {}

        normalized: dict[str, dict[str, Any]] = {}
        for raw_key, raw_slot in raw_group.items():
            slot_key = cls._normalize_slot_key(str(raw_key))
            if not slot_key or not isinstance(raw_slot, dict):
                continue

            value = str(raw_slot.get("value", "") or "").strip()
            updated_at = str(raw_slot.get("updated_at", "") or "")
            history_items = raw_slot.get("history", [])
            history: list[dict[str, str]] = []
            if isinstance(history_items, list):
                for item in history_items:
                    if not isinstance(item, dict):
                        continue
                    hist_value = str(item.get("value", "") or "").strip()
                    if not hist_value:
                        continue
                    history.append({
                        "value": hist_value,
                        "timestamp": str(item.get("timestamp", "") or ""),
                        "status": str(item.get("status", "") or "superseded"),
                        "reason": str(item.get("reason", "") or ""),
                    })

            confidence = raw_slot.get("confidence")
            if isinstance(confidence, (int, float)):
                confidence_value: float | None = max(0.0, min(1.0, float(confidence)))
            else:
                confidence_value = None

            if not value and not history:
                continue

            normalized[slot_key] = {
                "value": value,
                "updated_at": updated_at,
                "history": history[-cls._MAX_SLOT_HISTORY:],
                "confidence": confidence_value,
            }

        return normalized

    def _profile_field_limit(self, field: str) -> int:
        return (
            self.max_profile_traits
            if field == "traits"
            else self.max_profile_preferences
        )

    def _compose_field_values(
        self,
        profile: dict[str, Any],
        field: str,
    ) -> list[str]:
        slot_group = profile.get("profile_slots", {}).get(field, {})
        slot_values: list[str] = []
        if isinstance(slot_group, dict):
            slot_entries = sorted(
                slot_group.values(),
                key=lambda slot: str(slot.get("updated_at", "") or ""),
                reverse=True,
            )
            for slot in slot_entries:
                current_value = str(slot.get("value", "") or "").strip()
                if current_value and current_value not in slot_values:
                    slot_values.append(current_value)

        freeform_key = f"freeform_{field}"
        values = list(slot_values)
        for item in profile.get(freeform_key, []):
            if item not in values:
                values.append(item)

        return values[:self._profile_field_limit(field)]

    def _normalize_profile(self, profile: Any) -> dict[str, Any]:
        raw_profile = profile if isinstance(profile, dict) else {}
        normalized = _default_profile()

        normalized["name"] = str(raw_profile.get("name", "") or "").strip()
        normalized["notes"] = str(raw_profile.get("notes", "") or "")[:self._MAX_NOTES_LENGTH]
        normalized["updated_at"] = str(raw_profile.get("updated_at", "") or "")

        for field in self._STRUCTURED_FIELDS:
            freeform_key = f"freeform_{field}"
            source_values = raw_profile.get(freeform_key)
            if source_values is None:
                source_values = raw_profile.get(field, [])
            normalized[freeform_key] = self._normalize_text_list(source_values)[
                : self._profile_field_limit(field)
            ]

        raw_slots = raw_profile.get("profile_slots", {})
        normalized["profile_slots"] = {
            "traits": self._normalize_slot_group(
                raw_slots.get("traits") if isinstance(raw_slots, dict) else {}
            ),
            "preferences": self._normalize_slot_group(
                raw_slots.get("preferences") if isinstance(raw_slots, dict) else {}
            ),
        }

        for field in self._STRUCTURED_FIELDS:
            normalized[field] = self._compose_field_values(normalized, field)

        return normalized

    @classmethod
    def _append_slot_history(
        cls,
        slot: dict[str, Any],
        value: str,
        timestamp: str,
        status: str,
        reason: str,
    ) -> None:
        text = str(value).strip()
        if not text:
            return

        history = slot.get("history", [])
        if not isinstance(history, list):
            history = []

        history.append({
            "value": text,
            "timestamp": timestamp,
            "status": status,
            "reason": reason,
        })
        slot["history"] = history[-cls._MAX_SLOT_HISTORY:]

    def _clear_slot_group_current_values(
        self,
        profile: dict[str, Any],
        field: str,
        reason: str,
    ) -> None:
        now = self._now_timestamp()
        slot_group = profile.get("profile_slots", {}).get(field, {})
        if not isinstance(slot_group, dict):
            return
        for slot in slot_group.values():
            current_value = str(slot.get("value", "") or "").strip()
            if not current_value:
                continue
            self._append_slot_history(
                slot,
                current_value,
                str(slot.get("updated_at", "") or now),
                "superseded",
                reason,
            )
            slot["value"] = ""
            slot["updated_at"] = now

    def _remove_matching_slot_values(
        self,
        profile: dict[str, Any],
        field: str,
        value: str,
    ) -> None:
        target = str(value).strip()
        if not target:
            return
        now = self._now_timestamp()
        slot_group = profile.get("profile_slots", {}).get(field, {})
        if not isinstance(slot_group, dict):
            return
        for slot in slot_group.values():
            current_value = str(slot.get("value", "") or "").strip()
            if current_value != target:
                continue
            self._append_slot_history(
                slot,
                current_value,
                str(slot.get("updated_at", "") or now),
                "removed",
                "freeform_remove",
            )
            slot["value"] = ""
            slot["updated_at"] = now

    def _update_structured_slot(
        self,
        profile: dict[str, Any],
        field: str,
        action: str,
        value: str,
        fact_key: str,
        previous_value: str = "",
    ) -> None:
        slot_group = profile.setdefault("profile_slots", {}).setdefault(field, {})
        slot_key = self._normalize_slot_key(fact_key)
        if not slot_key:
            return

        slot = slot_group.setdefault(slot_key, {
            "value": "",
            "updated_at": "",
            "history": [],
            "confidence": None,
        })
        current_value = str(slot.get("value", "") or "").strip()
        current_updated_at = str(slot.get("updated_at", "") or "")
        new_value = str(value).strip()
        previous_text = str(previous_value).strip()
        now = self._now_timestamp()

        if action == "remove":
            if current_value:
                self._append_slot_history(
                    slot,
                    current_value,
                    current_updated_at or now,
                    "removed",
                    "explicit_remove",
                )
            slot["value"] = ""
            slot["updated_at"] = now
            return

        if not new_value:
            return

        if not current_value and previous_text and previous_text != new_value:
            self._append_slot_history(
                slot,
                previous_text,
                now,
                "superseded",
                "provided_previous_value",
            )

        if current_value and current_value != new_value:
            self._append_slot_history(
                slot,
                current_value,
                current_updated_at or now,
                "superseded",
                "profile_update",
            )

        if current_value != new_value:
            slot["value"] = new_value
            slot["updated_at"] = now
        elif not current_updated_at:
            slot["updated_at"] = now

    @classmethod
    def _slot_updated_within_days(
        cls,
        slot: dict[str, Any],
        max_days: int,
    ) -> bool:
        updated_at = str(slot.get("updated_at", "") or "")
        if not updated_at:
            return False
        try:
            ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        except (ValueError, TypeError):
            return False
        return age_days <= max_days

    @classmethod
    def _format_recent_slot_change_hints(
        cls,
        profile: dict[str, Any],
        max_items: int = 2,
    ) -> list[str]:
        slot_root = profile.get("profile_slots", {})
        if not isinstance(slot_root, dict):
            return []

        changes: list[tuple[str, str, str, str, str]] = []
        for field in cls._STRUCTURED_FIELDS:
            slot_group = slot_root.get(field, {})
            if not isinstance(slot_group, dict):
                continue
            for slot_key, slot in slot_group.items():
                history = slot.get("history", [])
                current_value = str(slot.get("value", "") or "").strip()
                if not current_value or not isinstance(history, list) or not history:
                    continue
                if not cls._slot_updated_within_days(
                    slot, cls._RECENT_SLOT_CHANGE_DAYS,
                ):
                    continue
                previous_value = str(history[-1].get("value", "") or "").strip()
                if not previous_value or previous_value == current_value:
                    continue
                changes.append((
                    str(slot.get("updated_at", "") or ""),
                    field,
                    slot_key,
                    current_value,
                    previous_value,
                ))

        changes.sort(key=lambda item: item[0], reverse=True)
        hints: list[str] = []
        for _updated_at, field, slot_key, current_value, previous_value in changes[:max_items]:
            label = "Preference" if field == "preferences" else "Trait"
            hints.append(
                f"Recent {label.lower()} update ({slot_key}): now {current_value}; previously {previous_value}"
            )
        return hints

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
        logger.info(
            "[LongTermMemory] resolved user context: session_key=%s user_key=%s kb_id=%s isolation=%s",
            session_key,
            user_key,
            kb_id,
            isolation,
        )
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

    def _get_cached_profile(self, storage_key: str) -> dict[str, Any] | None:
        now = time.monotonic()
        cached = self._profile_cache.get(storage_key)
        if not cached:
            return None

        cached_at, profile = cached
        if now - cached_at >= self._PROFILE_CACHE_TTL:
            self._profile_cache.pop(storage_key, None)
            return None

        self._profile_cache.move_to_end(storage_key)
        return profile

    def _set_cached_profile(self, storage_key: str, profile: dict[str, Any]) -> None:
        self._profile_cache[storage_key] = (time.monotonic(), profile)
        self._profile_cache.move_to_end(storage_key)
        while len(self._profile_cache) > self._MAX_PROFILE_CACHE_SIZE:
            self._profile_cache.popitem(last=False)

    async def _load_profile_by_storage_key(self, storage_key: str) -> dict[str, Any]:
        cached = self._get_cached_profile(storage_key)
        if cached is not None:
            return cached

        profile = await self._read_json(storage_key)
        if not profile:
            profile = _default_profile()
            await self._write_json(storage_key, profile)
        profile = self._normalize_profile(profile)
        self._set_cached_profile(storage_key, profile)
        return profile

    async def _save_profile_by_storage_key(
        self, storage_key: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        profile = self._normalize_profile(profile)
        profile["updated_at"] = self._now_timestamp()
        await self._write_json(storage_key, profile)
        self._set_cached_profile(storage_key, profile)
        return profile

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
        fact_key: str = "",
        previous_value: str = "",
    ) -> dict[str, Any]:
        profile = copy.deepcopy(
            await self._load_profile_by_storage_key(storage_key)
        )

        if field == "name":
            profile["name"] = value
        elif field in self._STRUCTURED_FIELDS:
            freeform_key = f"freeform_{field}"
            items: list[str] = self._normalize_text_list(profile.get(freeform_key, []))
            if fact_key:
                slot_key = self._normalize_slot_key(fact_key)
                old_slot = profile.get("profile_slots", {}).get(field, {}).get(slot_key, {})
                old_slot_value = str(old_slot.get("value", "") or "").strip()
                self._update_structured_slot(
                    profile,
                    field,
                    action,
                    value,
                    fact_key,
                    previous_value,
                )
                new_slot = profile.get("profile_slots", {}).get(field, {}).get(slot_key, {})
                new_slot_value = str(new_slot.get("value", "") or "").strip()
                profile[freeform_key] = [
                    item for item in items
                    if item not in {
                        old_slot_value,
                        new_slot_value,
                        str(previous_value).strip(),
                    }
                ]
            elif action == "add":
                if value not in items:
                    items.append(value)
                    items = items[-self._profile_field_limit(field):]
                profile[freeform_key] = items
            elif action == "remove":
                profile[freeform_key] = [i for i in items if i != value]
                self._remove_matching_slot_values(profile, field, value)
            elif action == "set":
                profile[freeform_key] = [value]
                self._clear_slot_group_current_values(
                    profile, field, "field_set_reset",
                )
            profile[field] = self._compose_field_values(profile, field)
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

        profile = await self._save_profile_by_storage_key(storage_key, profile)
        return profile

    async def update_session_profile_field(
        self,
        scope_key: str,
        field: str,
        action: str,
        value: str,
        fact_key: str = "",
        previous_value: str = "",
    ) -> dict[str, Any]:
        return await self._update_profile_field_by_storage_key(
            self._session_profile_key(scope_key),
            field,
            action,
            value,
            fact_key,
            previous_value,
        )

    async def update_speaker_profile_field(
        self,
        scope_key: str,
        sender_id: str,
        field: str,
        action: str,
        value: str,
        fact_key: str = "",
        previous_value: str = "",
    ) -> dict[str, Any]:
        return await self._update_profile_field_by_storage_key(
            self._speaker_profile_key(scope_key, sender_id),
            field,
            action,
            value,
            fact_key,
            previous_value,
        )

    async def clear_session_profile(self, scope_key: str) -> None:
        await self._save_profile_by_storage_key(
            self._session_profile_key(scope_key), _default_profile()
        )

    async def clear_speaker_profile(self, scope_key: str, sender_id: str) -> None:
        await self._save_profile_by_storage_key(
            self._speaker_profile_key(scope_key, sender_id), _default_profile()
        )

    async def export_profiles_by_scope(
        self, scope_key: str
    ) -> list[dict[str, Any]]:
        """Export L1 profiles that belong to *scope_key*.

        Only profiles whose storage key matches the given scope_key are
        returned, preventing cross-session / cross-user data leakage.

        Returns a list of dicts, each containing type, scope_key,
        optional sender_id, and profile data.
        """
        keys: list[str] = await self.plugin.get_plugin_storage_keys()
        profiles: list[dict[str, Any]] = []

        session_storage_key = self._session_profile_key(scope_key)
        speaker_prefix = f"pp:{scope_key}:"

        for key in keys:
            if key == session_storage_key:
                profile = self._normalize_profile(await self._read_json(key))
                if profile and self.has_profile_data(profile):
                    entry: dict[str, Any] = {
                        "type": "session",
                        "scope_key": scope_key,
                        "profile": copy.deepcopy(profile),
                    }
                    profiles.append(entry)

            elif key.startswith(speaker_prefix):
                sender_id = key[len(speaker_prefix):]
                if not sender_id:
                    continue
                profile = self._normalize_profile(await self._read_json(key))
                if profile and self.has_profile_data(profile):
                    entry = {
                        "type": "speaker",
                        "scope_key": scope_key,
                        "sender_id": sender_id,
                        "profile": copy.deepcopy(profile),
                    }
                    profiles.append(entry)

        return profiles

    # ======================== L2: episodes (ChromaDB vector) ========================

    _SUPERSEDE_IMPORTANCE_FACTOR = 0.1  # multiplied onto old importance

    async def _auto_supersede(
        self,
        collection_id: str,
        embedding_model_uuid: str,
        query_vector: list[float],
        user_key: str,
        new_episode_id: str,
        similarity_threshold: float = 0.85,
        max_candidates: int = 5,
    ) -> int:
        """Find similar older episodes and mark them as superseded.

        Superseding means re-upserting the old vector with:
        - importance reduced by _SUPERSEDE_IMPORTANCE_FACTOR
        - 'superseded_by' metadata field set to new_episode_id

        Returns the number of superseded episodes.
        """
        filters: dict[str, Any] = {"user_key": user_key}
        results = await self.plugin.vector_search(
            collection_id=collection_id,
            query_vector=query_vector,
            top_k=max_candidates + 1,  # +1 because the new episode itself may appear
            filters=filters,
        )

        superseded = 0
        for r in results:
            rid = r.get("id", "")
            if rid == new_episode_id:
                continue
            meta = r.get("metadata", {})
            # Already superseded — skip
            if meta.get("superseded_by"):
                continue

            # Check similarity: distance is cosine distance (lower = more similar)
            distance = r.get("distance", 1.0)
            similarity = 1.0 - distance
            if similarity < similarity_threshold:
                continue

            # Re-upsert with reduced importance and superseded_by marker
            old_importance = int(meta.get("importance", "2"))
            new_importance = max(1, int(old_importance * self._SUPERSEDE_IMPORTANCE_FACTOR))
            meta["importance"] = str(new_importance)
            meta["superseded_by"] = new_episode_id

            # We need the original vector; re-embed from content
            old_content = meta.get("content", "")
            if not old_content:
                continue
            old_vectors = await self.plugin.invoke_embedding(embedding_model_uuid, [old_content])

            await self.plugin.vector_upsert(
                collection_id=collection_id,
                vectors=old_vectors,
                ids=[rid],
                metadata=[meta],
                documents=[old_content],
            )
            superseded += 1
            logger.info(
                "[LongTermMemory] auto_supersede: episode %s superseded by %s (similarity=%.3f, importance %s->%s)",
                rid,
                new_episode_id,
                similarity,
                old_importance,
                new_importance,
            )

        return superseded

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
        logger.info(
            "[LongTermMemory] add_episode: collection_id=%s user_key=%s sender_id=%s importance=%s tags=%s content_len=%s",
            collection_id,
            user_key,
            sender_id,
            importance,
            tags,
            len(content),
        )

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
        logger.info(
            "[LongTermMemory] add_episode stored: collection_id=%s episode_id=%s timestamp=%s",
            collection_id,
            episode_id,
            timestamp,
        )

        # Auto-supersede: when the new episode is a correction / fact-update /
        # clarification, search for similar older episodes in the same scope and
        # mark them as superseded by lowering their importance.
        _SUPERSEDE_TAGS = {"correction", "fact-update", "clarification"}
        if _SUPERSEDE_TAGS & set(tags):
            try:
                await self._auto_supersede(
                    collection_id=collection_id,
                    embedding_model_uuid=embedding_model_uuid,
                    query_vector=vectors[0],
                    user_key=user_key,
                    new_episode_id=episode_id,
                    similarity_threshold=0.85,
                )
            except Exception:
                logger.warning(
                    "[LongTermMemory] auto_supersede failed for episode %s, skipping",
                    episode_id,
                    exc_info=True,
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
        logger.info(
            "[LongTermMemory] search_episodes: collection_id=%s user_key=%s sender_id=%s sender_name=%s top_k=%s source=%s importance_min=%s time_after=%s time_before=%s query_len=%s",
            collection_id,
            user_key,
            sender_id,
            sender_name,
            top_k,
            source,
            importance_min,
            time_after,
            time_before,
            len(query),
        )

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
                time_filter["$gte"] = self.normalize_timestamp(time_after)
            if time_before:
                time_filter["$lte"] = self.normalize_timestamp(time_before)
            filters["timestamp"] = time_filter
        if importance_min is not None:
            # importance is stored as a string ("1"-"5") in vector DB metadata;
            # string comparison works correctly for single-digit values in this range.
            filters["importance"] = {"$gte": str(importance_min)}

        # ChromaDB requires $and wrapper when there are multiple filter conditions
        if len(filters) > 1:
            filters = {"$and": [{k: v} for k, v in filters.items()]}

        results = await self.plugin.vector_search(
            collection_id=collection_id,
            query_vector=query_vector,
            top_k=top_k,
            filters=filters if filters else None,
        )
        logger.info(
            "[LongTermMemory] search_episodes completed: collection_id=%s result_count=%s filters=%s",
            collection_id,
            len(results),
            filters if filters else None,
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

    async def list_episodes(
        self,
        collection_id: str,
        user_key: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List episodic memories for a user with pagination.

        Returns:
            Tuple of (episodes, total).
        """
        filters: dict[str, Any] = {"user_key": user_key}
        result = await self.plugin.vector_list(
            collection_id=collection_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )
        items = result.get("items", [])
        total = result.get("total", -1)

        episodes = []
        for item in items:
            meta = item.get("metadata", {})
            episodes.append({
                "id": item.get("id", ""),
                "content": meta.get("content", "") or item.get("document", ""),
                "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                "importance": int(meta.get("importance", "2")),
                "timestamp": meta.get("timestamp", ""),
                "sender_id": meta.get("sender_id", ""),
                "sender_name": meta.get("sender_name", ""),
                "source": meta.get("source", ""),
            })
        return episodes, total

    async def delete_episode_by_id(
        self,
        collection_id: str,
        episode_id: str,
        user_key: str,
    ) -> int:
        """Delete a single episode by its ID, scoped to user_key for safety."""
        filters: dict[str, Any] = {
            "$and": [
                {"user_key": user_key},
            ]
        }
        return await self.plugin.vector_delete(
            collection_id=collection_id,
            file_ids=[episode_id],
            filters=filters,
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
        for hint in MemoryStore._format_recent_slot_change_hints(profile, max_items=3):
            parts.append(f"- {hint}")
        if profile.get("notes"):
            parts.append(f"- Notes: {profile['notes']}")
        if profile.get("updated_at"):
            parts.append(f"- Last updated: {profile['updated_at']}")

        return "\n".join(parts)
