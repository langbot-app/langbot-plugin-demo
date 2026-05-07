from __future__ import annotations

import json
import os
from pathlib import Path

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import context, events
from langbot_plugin.api.entities.builtin.platform import message as platform_message


class EBAEventProbeListener(EventListener):
    def __init__(self):
        super().__init__()
        self.log_path = Path(os.getenv("EBA_PROBE_LOG", "eba_event_probe.jsonl"))
        self.api_probe_enabled = os.getenv("EBA_PROBE_API") == "1"
        self.api_probe_done = False

        for event_type in (
            events.MessageReceived,
            events.MessageEdited,
            events.MessageDeleted,
            events.MessageReactionReceived,
            events.FeedbackReceived,
            events.GroupMemberJoined,
            events.GroupMemberLeft,
            events.GroupMemberBanned,
            events.BotInvitedToGroup,
            events.BotRemovedFromGroup,
            events.BotMuted,
            events.BotUnmuted,
            events.PlatformSpecificEventReceived,
        ):
            self.handler(event_type)(self._record)

    async def _record(self, event_context: context.EventContext):
        record = {
            "event_name": event_context.event_name,
            "query_id": event_context.query_id,
            "event": event_context.event.model_dump(),
        }
        with self.log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"EBA_PROBE_EVENT {event_context.event_name}")

        if (
            self.api_probe_enabled
            and not self.api_probe_done
            and isinstance(event_context.event, events.MessageReceived)
        ):
            self.api_probe_done = True
            await self._probe_plugin_apis(event_context.event)

    async def _probe_plugin_apis(self, event: events.MessageReceived):
        api_result = {"event_name": "APIProbe", "ok": True, "calls": []}

        try:
            version = await self.plugin.get_langbot_version()
            api_result["calls"].append({"name": "get_langbot_version", "result": version})

            bots = await self.plugin.get_bots()
            api_result["calls"].append({"name": "get_bots", "result": bots})

            if bots:
                selected_bot = next((bot for bot in bots if isinstance(bot, dict) and bot.get("enable")), bots[0])
                selected_bot_uuid = selected_bot["uuid"] if isinstance(selected_bot, dict) else selected_bot

                bot_info = await self.plugin.get_bot_info(selected_bot_uuid)
                api_result["calls"].append({"name": "get_bot_info", "result": bot_info})

                target_type = "group" if event.chat_type == "group" else "person"
                await self.plugin.send_message(
                    selected_bot_uuid,
                    target_type,
                    event.chat_id,
                    platform_message.MessageChain(
                        [platform_message.Plain(text="EBA API probe message")]
                    ),
                )
                api_result["calls"].append({"name": "send_message", "result": "ok"})

            await self.plugin.set_plugin_storage("eba_probe_plugin", b"plugin-value")
            plugin_value = await self.plugin.get_plugin_storage("eba_probe_plugin")
            plugin_keys = await self.plugin.get_plugin_storage_keys()
            await self.plugin.delete_plugin_storage("eba_probe_plugin")
            api_result["calls"].append(
                {
                    "name": "plugin_storage",
                    "result": {"value": plugin_value.decode("utf-8"), "keys": plugin_keys},
                }
            )

            await self.plugin.set_workspace_storage("eba_probe_workspace", b"workspace-value")
            workspace_value = await self.plugin.get_workspace_storage("eba_probe_workspace")
            workspace_keys = await self.plugin.get_workspace_storage_keys()
            await self.plugin.delete_workspace_storage("eba_probe_workspace")
            api_result["calls"].append(
                {
                    "name": "workspace_storage",
                    "result": {
                        "value": workspace_value.decode("utf-8"),
                        "keys": workspace_keys,
                    },
                }
            )

            manifests = await self.plugin.list_plugins_manifest()
            commands = await self.plugin.list_commands()
            tools = await self.plugin.list_tools()
            knowledge_bases = await self.plugin.list_knowledge_bases()
            api_result["calls"].extend(
                [
                    {"name": "list_plugins_manifest", "result": manifests},
                    {"name": "list_commands", "result": commands},
                    {"name": "list_tools", "result": tools},
                    {"name": "list_knowledge_bases", "result": knowledge_bases},
                ]
            )
        except Exception as exc:
            api_result["ok"] = False
            api_result["error"] = repr(exc)

        with self.log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(api_result, ensure_ascii=False) + "\n")
        print(f"EBA_PROBE_API {'OK' if api_result['ok'] else 'FAILED'}")
