# EBA Event Probe

EBA Event Probe is a test plugin for the Event-Based Agent architecture. It registers one `EventListener` and records every supported EBA platform event it receives.

It is useful when validating:

- whether LangBot forwards platform EBA events into the plugin runtime;
- whether plugin API calls still work from an EBA event handler;
- whether a standalone runtime can deliver EBA events to plugin listeners;
- whether new platform adapters expose the expected event coverage.

## Events

The listener currently records:

- `MessageReceived`
- `MessageEdited`
- `MessageReactionReceived`
- `FeedbackReceived`
- `GroupMemberJoined`
- `GroupMemberLeft`
- `GroupMemberBanned`
- `BotInvitedToGroup`
- `BotRemovedFromGroup`
- `BotMuted`
- `BotUnmuted`
- `PlatformSpecificEventReceived`

## Output

Each received event is appended as one JSON object per line:

```json
{"event_name":"MessageReceived","query_id":0,"event":{}}
```

Set `EBA_PROBE_LOG` to change the log path. If it is not set, the plugin writes to `eba_event_probe.jsonl` in the current working directory.

## API Probe

Set `EBA_PROBE_API=1` to make the listener call plugin APIs after the first `MessageReceived` event:

- `get_langbot_version`
- `get_bots`
- `get_bot_info`
- `send_message`
- plugin storage set/get/list/delete
- workspace storage set/get/list/delete
- `list_plugins_manifest`
- `list_commands`
- `list_tools`
- `list_knowledge_bases`

Query-based APIs such as `EventContext.reply()` are intentionally not called by this EBA probe because standalone EBA platform events do not have a pipeline query context.

## Standalone Runtime

Start the runtime:

```bash
lbp rt --debug-only
```

Copy `.env.example` to `.env`, adjust `DEBUG_RUNTIME_WS_URL` if needed, then run the plugin:

```bash
lbp run
```

Run the standalone probe driver from this plugin directory to verify both event delivery and API calls:

```bash
python scripts/standalone_runtime_probe.py
```
