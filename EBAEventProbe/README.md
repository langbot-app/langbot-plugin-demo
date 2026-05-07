# EBA Event Probe

EBA Event Probe is a test plugin for the Event-Based Agent architecture. It registers one `EventListener` and records every supported EBA platform event it receives.

It is useful when validating:

- whether LangBot forwards platform EBA events into the plugin runtime;
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

## Standalone Runtime

Start the runtime:

```bash
lbp rt --debug-only
```

Copy `.env.example` to `.env`, adjust `DEBUG_RUNTIME_WS_URL` if needed, then run the plugin:

```bash
lbp run
```
