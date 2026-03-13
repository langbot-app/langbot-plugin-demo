# LongTermMemory

Long-term memory plugin for LangBot with a dual-layer design:

- L1 core profile injected into the system prompt
- L2 episodic memory retrieved through the KnowledgeEngine and vector database

## What It Does

- Exposes a `remember` tool for episodic memory writes
- Exposes a `recall_memory` tool for active episodic memory lookup with controlled filters
- Exposes an `update_profile` tool for stable profile updates
- Injects profile memory and current speaker identity through an EventListener
- Uses a KnowledgeEngine to retrieve relevant episodic memories before model invocation
- Provides a `!memory` command for inspection and debugging

## Design

This plugin intentionally stays close to LangBot's existing extension points instead of requiring custom core patches.

- L1 profile is stored in plugin storage as JSON
- L2 episodic memory is stored in the vector database
- Memory retrieval is enabled per pipeline by attaching this plugin's KnowledgeEngine
- The plugin currently assumes a single memory KB per plugin instance and isolates memory by metadata

The current implementation is built around the existing LangBot and SDK APIs. If LangBot later adds more explicit memory-oriented APIs, session identity APIs, or KB registration APIs, the plugin could be simplified, but the current architecture would still remain valid.

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

## How To Use

1. Install and enable the plugin.
2. Create one memory knowledge base with this plugin's KnowledgeEngine.
3. Configure:
   - `embedding_model_uuid`
   - `isolation`
   - optional `max_results`
4. Let the agent use:
   - `remember` for events, plans, and episodic facts
   - `recall_memory` for active memory lookup when automatic recall is insufficient
   - `update_profile` for stable preferences and profile data
5. Use `!memory`, `!memory profile`, and `!memory search <query>` to inspect behavior.

## Components

- KnowledgeEngine: [`memory_engine.py`](/home/yhh/workspace/langbot-plugin-memory/components/knowledge_engine/memory_engine.py)
- EventListener: [`memory_injector.py`](/home/yhh/workspace/langbot-plugin-memory/components/event_listener/memory_injector.py)
- Tools: [`remember.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/remember.py), [`recall_memory.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/recall_memory.py), [`update_profile.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/update_profile.py)
- Command: [`memory.py`](/home/yhh/workspace/langbot-plugin-memory/components/commands/memory.py)

## Current Gaps

Compared with the demo plugins, this plugin was mainly missing user-facing documentation. The main missing pieces were:

- root `README.md`
- localized `readme/` docs

The manifest, icon, tool YAMLs, command YAML, and KnowledgeEngine schema are already present.
