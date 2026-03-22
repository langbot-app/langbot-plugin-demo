# LongTermMemory

Long-term memory plugin for LangBot with a dual-layer design:

- L1 core profile injected into the system prompt
- L2 episodic memory retrieved through vector search and injected into context

## What It Does

- Exposes a `remember` tool for episodic memory writes
- Exposes a `recall_memory` tool for active episodic memory lookup with controlled filters
- Exposes an `update_profile` tool for stable profile updates
- Exposes a `forget` tool for agent-initiated deletion of specific episodic memories
- Injects profile memory and current speaker identity through an EventListener
- Uses an EventListener to retrieve and inject relevant episodic memories before model invocation
- Provides a `!memory` command for inspection and debugging
- Provides `!memory list [page]` to browse episodic memories with pagination
- Provides `!memory forget <episode_id>` to delete a specific episode
- Provides `!memory search <query>` to search episodes (results include episode IDs)
- Provides a `!memory export` command to export L1 profiles for the current session as JSON
- Automatically supersedes related older episodes when a correction/fact-update/clarification is stored

## Overall Design

This plugin is not trying to dump the entire chat history into context. Instead, it splits long-term memory into two layers with different storage and retrieval behavior:

- **L1 core profile**: stable, low-frequency facts such as names, preferences, identity, and long-lived notes
- **L2 episodic memory**: time-sensitive and situational facts such as recent events, plans, and experiences

This split exists for a reason:

- Stable profile data is cheap and reliable to inject into the system prompt
- Episodic memory keeps growing over time, so it should be retrieved on demand instead of fully injected every turn
- Agents should update stable profile facts differently from event-like memories

## How This Differs From OpenClaw-Style Personal Assistant Memory

Recently, a lot of agent systems have discussed designs like OpenClaw: long-term memory stored primarily as user-readable text files such as `MEMORY.md`, combined with summaries, reflection, and light retrieval logic.

That approach has clear strengths:

- memory is fully transparent to the user
- plain text is naturally easy to back up, sync, and version-control
- it fits single-user, single-assistant, high-continuity personal workflows very well
- when memory volume stays small, full-text understanding can indeed be "good enough"

But LongTermMemory in LangBot is solving a different problem. Typical LangBot deployment looks more like:

- one bot serving multiple group chats and private chats
- one plugin instance handling multiple sessions and multiple speakers
- memory including shared group context, current-speaker profile, and session-level episodic facts
- explicit isolation boundaries between sessions, bots, and speakers

Because of that, we did not adopt a "single text file as the source of truth" design. We chose a layered architecture that better matches LangBot's multi-session runtime model.

### What OpenClaw-like memory is optimized for

Abstractly, that design is optimized for:

- **single-user personal assistants**
- **human-readable text as the primary long-term memory form**
- **transparency, editability, and narrative continuity**
- **an assumption that memory size stays manageable and the user is willing to curate it directly**

That is a very reasonable fit for personal AI companions, research copilots, and private assistant workflows.

### Why LangBot does not simply copy that model

LongTermMemory is designed around different operating constraints: multiple sessions, multiple speakers, explicit isolation, controlled injection, and retrievable episodic recall.

If we turned long-term memory into one narrative file like `MEMORY.md`, several problems would appear quickly:

- **Isolation would become hard**
  - how should memories from group A, group B, and private chat C coexist safely?
  - how do you cleanly separate one speaker's stable profile from a shared narrative log?
- **Injection granularity would become unstable**
  - system prompts need stable profile state, not an entire chronological diary
  - automatic recall needs the most relevant memory slices for the current query, not the whole story
- **Multi-user boundaries are first-class in LangBot**
  - in a personal assistant, "the user" is usually one person
  - in LangBot, current speaker, current session, and current bot all matter
- **Automatic injection and active retrieval are different needs**
  - stable profile data should be injected consistently
  - episodic memory should be retrieved selectively
  - forcing both into one text-only memory shape becomes awkward

### The tradeoff we made

So the LongTermMemory design is essentially this tradeoff:

- **What we borrow from that philosophy**
  - memory should not be treated as only a black-box vector store
  - stable profile, temporal memory, and long-term behavior adjustment all matter
  - not everything should be dumped into context every turn

- **Where we deliberately differ**
  - we do not use a narrative text diary as the only memory source of truth
  - we split stable profile and episodic memory explicitly
  - we prioritize isolation across sessions, speakers, and bots
  - we let L2 memory plug naturally into LangBot's KB / retrieval system instead of relying only on full-text reading

In short:

- OpenClaw is mainly answering: "How should a personal assistant keep readable, editable, reflective long-term memory?"
- LongTermMemory is mainly answering: "How should a bot working across groups and private chats keep stable profile state and retrievable experience memory under explicit isolation rules?"

Neither direction is universally "better". They optimize for different products and different failure modes.

## Design

This plugin intentionally stays close to LangBot's existing extension points instead of requiring custom core patches.

- L1 profile is stored in plugin storage as JSON
- L2 episodic memory is stored in the vector database
- Memory retrieval is enabled per pipeline by attaching this plugin's KnowledgeEngine
- The plugin currently assumes a single memory KB per plugin instance and isolates memory by metadata

The current implementation is built around the existing LangBot and SDK APIs. If LangBot later adds more explicit memory-oriented APIs, session identity APIs, or KB registration APIs, the plugin could be simplified, but the current architecture would still remain valid.

### Vector Database Backend Compatibility

L2 episodic memory relies on arbitrary metadata fields (`user_key`, `episode_id`, `tags`, `importance`, etc.) for isolation and filtering. Not all LangBot vector database backends support arbitrary metadata:

| Backend | Arbitrary metadata | LongTermMemory support |
|---------|-------------------|----------------------|
| **Chroma** (default) | Yes | Full support |
| **Qdrant** | Yes | Full support |
| **SeekDB** | Yes | Full support |
| **Milvus** | No (fixed schema: `text`, `file_id`, `chunk_uuid`) | Not supported |
| **pgvector** | No (fixed schema: `text`, `file_id`, `chunk_uuid`) | Not supported |

Milvus and pgvector use a fixed column schema and silently drop metadata fields they do not recognize. This means metadata-based isolation (`user_key` filtering) and episodic memory commands (`!memory list`, `!memory forget`, `!memory search`) will not work correctly on these backends — filters will be ignored and queries may return unscoped results.

If you need to use LongTermMemory, use Chroma, Qdrant, or SeekDB as your vector database backend.

## How It Works

An end-to-end long-term memory flow has four main parts:

### 1. L1 profile writes

- The agent uses `update_profile` to write stable facts
- Data is stored in plugin storage as structured JSON
- Profiles are stored at either `session` or `speaker` scope

### 2. L2 episodic writes

- The agent uses `remember` to write event-like memory
- Each memory carries metadata such as timestamp, importance, tags, and scope
- Those memories are embedded and stored in the vector database through the plugin's KnowledgeEngine

### 3. Automatic pre-response injection

- During `PromptPreProcessing`, the EventListener resolves the current session identity
- For L1:
  - it loads the shared session profile
  - it loads the current speaker profile
  - it injects both, along with current speaker identity, into `default_prompt`
- For L2:
  - it runs one episodic retrieval using the current user message
  - retrieved memories are injected as factual context blocks

So both L1 and L2 enter the model context before answer generation, but in different forms: L1 as system prompt memory, L2 as retrieved context.

### 4. Active lookup and debugging

- If automatic injection is insufficient, the agent can call `recall_memory`
- For inspection and debugging, you can use `!memory`, `!memory profile`, `!memory search`, `!memory list`, and `!memory forget`
- `!memory export` exports only the current scope's L1 profiles for backup or migration

## Relationship With AgenticRAG

When AgenticRAG is enabled together with LongTermMemory:

- LongTermMemory removes its own memory KB from naive RAG pre-processing
- automatic L2 recall is still handled by LongTermMemory itself
- the same memory KB can still be queried explicitly through AgenticRAG's `query_knowledge` tool

This avoids duplicate recall while preserving both paths:

- automatic memory recall
- deeper agent-initiated retrieval when needed

## Why There Is No Agent-Side Metadata Filter

The underlying runtime can support metadata filtering, but this plugin does not expose arbitrary raw metadata filters to the agent flow today.

Reasons:

- Different knowledge engines and vector backends do not share one unified metadata schema
- Filter field names, value formats, and supported operators may differ
- The agent currently has no stable schema source for constructing reliable filters

If LangBot later provides a unified way to describe filterable metadata fields per knowledge base, agent-side metadata filtering can be added.

This plugin does provide a controlled recall tool surface for its own stable memory schema. That tool supports selected filters such as speaker and time range, without exposing free-form backend-specific filter syntax to the model.

## Isolation Model

Two isolation modes are supported:

- `session`: each group chat or private chat has independent memory
- `bot`: all sessions under the same bot share memory

In the current deployment model, this is generally sufficient because plugin instances are usually bound to a specific LangBot runtime/bot environment.

## Isolation Rules In Detail

There are two related but slightly different scope concepts in this plugin:

- **session_name**: the conversation identity passed through the current query / retrieval path, formatted as `{launcher_type}_{launcher_id}`
- **session_key**: the plugin's internal L1 storage key. When `bot_uuid` is available, it becomes `{bot_uuid}:{launcher_type}_{launcher_id}`; otherwise it falls back to `{launcher_type}_{launcher_id}`
- **scope_key / user_key**: the actual key used for profile storage or L2 retrieval isolation

### How L1 profiles are isolated

L1 profiles are always stored within the current conversation scope:

- `session profile`
  - shared profile for the current conversation
  - useful for group-level or conversation-level stable context
- `speaker profile`
  - stable facts about the current speaker
  - useful for person-specific preferences, identity, and notes

Because of that, `!memory export` exports only the profiles that belong to the current `session_key`, not every profile in the whole plugin instance.

### How L2 episodic memory is isolated

L2 memories are written into the vector store with isolation metadata, then filtered at retrieval time:

- `session`
  - memories from group A are not recalled in group B
  - memories from one private chat are not recalled in another
- `bot`
  - all sessions under the same bot share one episodic memory space
  - useful when you want cross-session long-term experience sharing

When `sender_id` is available, the plugin can also prefer speaker-related memories before widening to the broader scope.

### Why L1 and L2 isolation are not exactly the same

That is intentional:

- L1 behaves like stable profile state, so precise session / speaker storage makes sense
- L2 behaves like a retrievable experience base, so metadata-based filtering is the more scalable model
- this keeps L1 precise and L2 flexible

## How To Use

1. Install and enable the plugin.
2. Create one memory knowledge base with this plugin's KnowledgeEngine.
3. Configure:
   - `embedding_model_uuid`
   - `isolation`
   - optional `recency_half_life_days`
   - optional `auto_recall_top_k`
4. Let the agent use:
   - `remember` for events, plans, and episodic facts
   - `recall_memory` for active memory lookup when automatic recall is insufficient
   - `update_profile` for stable preferences and profile data
   - `forget` to delete a specific episodic memory by ID
5. Use `!memory`, `!memory profile`, `!memory search <query>`, `!memory list [page]`, `!memory forget <id>`, and `!memory export` to inspect behavior.

## Context Sharing for Other Plugins

LongTermMemory writes a structured context summary to the query variable `_ltm_context` during every `PromptPreProcessing` event. Other plugins can read this variable to make programmatic decisions based on user memory, without importing or referencing LongTermMemory in any way.

### Variable Key

`_ltm_context`

### Schema

```python
{
    "speaker": {
        "id": "user_123",           # sender_id, may be empty string
        "name": "Alice",            # sender_name, may be empty string
    },
    "session_profile": {            # always present, fields may be empty
        "name": "",
        "traits": ["creative", "analytical"],
        "preferences": ["prefers detailed explanations"],
        "notes": "",
        "updated_at": "2025-03-16T12:00:00Z",
    },
    "speaker_profile": {            # null when sender_id is unavailable
        "name": "Alice",
        "traits": ["extroverted"],
        "preferences": ["likes humor"],
        "notes": "",
        "updated_at": "2025-03-16T12:00:00Z",
    },
    "episodes": [                   # auto-recalled L2 episodic memories, may be empty
        {"content": "User mentioned a trip to Beijing last week"},
    ],
}
```

### Usage Example

```python
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.entities.builtin.provider.message import Message


class PersonalityCustomizer(EventListener):
    def __init__(self):
        super().__init__()

        @self.handler(events.PromptPreProcessing)
        async def on_prompt(event_ctx: context.EventContext):
            ltm = await event_ctx.get_query_var("_ltm_context")
            if not ltm:
                # LongTermMemory not installed or inactive — use defaults
                return

            profile = ltm.get("speaker_profile") or ltm.get("session_profile") or {}
            traits = profile.get("traits", [])

            if "喜欢幽默" in traits:
                style = "Use a humorous and playful tone."
            elif "偏好简洁" in traits:
                style = "Be concise and direct."
            else:
                return

            event_ctx.event.default_prompt.append(
                Message(role="system", content=style)
            )
```

### Design Notes

- If LongTermMemory is not installed, `_ltm_context` does not exist. Consuming plugins should treat `None` as normal and fall back to default behavior.
- If LongTermMemory is active but no profile data has been stored yet, the variable exists with empty fields. This lets consuming plugins distinguish "no memory plugin" from "memory plugin active, no data yet".
- Both sides depend only on the variable key and schema convention, not on each other's code. If LongTermMemory is replaced by another memory plugin that writes the same key with the same schema, consuming plugins continue to work.
- LongTermMemory must run before consuming plugins in the event dispatch order. In practice this depends on plugin installation order.

## Import / Export

- **Export (L1 profiles):** Use `!memory export` to export the current scope's session and speaker profiles as JSON. It does not export data from other sessions or scopes.
- **Import (L2 episodic memory):** Upload a JSON file through the LangBot knowledge base UI to bulk-import episodic memories.
- **L2 episodic memory can be browsed** via `!memory list [page]` and individual episodes deleted via `!memory forget <id>`. Full bulk export is not yet implemented.

## Key Technical Q&A

### Q1. Why split memory into L1 and L2 instead of storing everything in the vector database?

Because the access patterns are different:

- L1 contains stable facts and should be injected consistently
- L2 contains event-like memory and should be retrieved on demand

Putting both into the vector store would make stable profile recall less reliable and make memory updates semantically messy.

### Q2. Why is L2 retrieved instead of fully injected every turn?

Because L2 grows over time. Full injection would quickly cause:

- prompt bloat
- too much irrelevant noise
- old memory crowding out the actually relevant context

The current strategy is to retrieve a small relevant subset automatically, then let the agent use `recall_memory` if it needs more.

### Q3. Does L2 memory decay over time?

Yes.

L2 ranking does not depend only on vector similarity. It also applies time decay so that newer memories tend to rank higher than older ones.

The current implementation uses a half-life style approach:

- when a memory reaches `half_life_days`, its time weight decays to roughly 50%
- newer memory is favored in ranking
- older memory is not deleted automatically; it just loses ranking advantage

This is meant to prioritize recent context, not to hard-delete the past.

### Q4. Do old memories eventually disappear completely?

Not automatically.

Time decay affects ranking, not hard deletion. Old memories can still be recalled if they remain relevant enough.

### Q5. How should I choose between `session` and `bot` isolation?

In practice:

- choose `session`
  - when each group chat / private chat should keep independent memory
  - when you want lower risk of cross-session leakage
- choose `bot`
  - when the bot should share long-term experience across sessions
  - when broader recall is more important than stricter separation

If you are unsure, start with `session`.

### Q6. Why does `!memory export` only export the current scope?

That is a deliberate safety boundary.

Allowing export of every L1 profile in the plugin instance would make cross-session data leakage much easier. Restricting export to the current scope follows a minimum-exposure principle.

### Q7. What happens if the runtime does not expose `_knowledge_base_uuids` in query variables?

Automatic memory injection still works, but the plugin cannot remove its memory KB from naive RAG pre-processing.

That can lead to duplicate memory recall:

- one copy injected by LongTermMemory itself
- another copy recalled again by the runner's generic KB flow

So this is not a full failure, but it can waste context and make the prompt noisier.

### Q8. Why is L2 export not supported yet?

The SDK now provides a `vector_list` API for paginated enumeration of vector store content. L2 episodic memories can be browsed via `!memory list [page]` and deleted individually via `!memory forget <episode_id>` or the `forget` tool.

Full bulk export is not yet implemented, but the building blocks are in place.

### Q9. Will LongTermMemory and AgenticRAG duplicate recall when both are enabled?

No, that duplication is exactly what the current design avoids:

- LongTermMemory removes its own naive RAG pre-processing
- automatic L2 recall is handled by LongTermMemory
- deeper ad hoc retrieval can still go through AgenticRAG

## Components

- KnowledgeEngine: [memory_engine.py](components/knowledge_engine/memory_engine.py)
- EventListener: [memory_injector.py](components/event_listener/memory_injector.py)
- Tools: [remember.py](components/tools/remember.py), [recall_memory.py](components/tools/recall_memory.py), [update_profile.py](components/tools/update_profile.py), [forget.py](components/tools/forget.py)
- Command: [memory.py](components/commands/memory.py)

## Current Gaps

The README now covers the core design, isolation rules, export boundaries, and major components.

Still worth adding later:

- synchronized updates for localized docs
- concrete JSON import examples
- best-practice examples for `remember`, `recall_memory`, and `update_profile`

## Logging

The plugin now emits logs at key memory lifecycle points so you can observe how long-term memory is being used during runtime.

You will see logs for:

- plugin initialization and resolved memory context
- `remember`, `recall_memory`, and `update_profile` tool calls
- profile injection before model invocation
- automatic L2 memory retrieval in the KnowledgeEngine
- episodic memory vector writes, searches, import batches, and deletes

Typical log messages look like:

```text
[LongTermMemory] remember called: query_id=123 params_keys=['content', 'importance', 'tags']
[LongTermMemory] memory injection ready: query_id=123 kb_id=kb-1 scope_key=bot:xxx:group_123 sender_id=u1 block_count=2 prompt_chars=280
[LongTermMemory] engine retrieve called: collection_id=kb-1 top_k=5 session_name=group_123 sender_id=u1 bot_uuid=bot-1 query='user asked about travel plan'
[LongTermMemory] search_episodes completed: collection_id=kb-1 result_count=3 filters={'user_key': 'bot:bot-1:group_123'}
```
