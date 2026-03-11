# AgenticRAG

AgenticRAG exposes the knowledge bases configured for the current pipeline as an LLM Tool, so an agent can inspect available KBs and retrieve relevant chunks on demand.

## What It Does

- Provides a single tool, `query_knowledge`
- Supports two actions:
  - `list`: list knowledge bases available to the current pipeline
  - `query`: retrieve relevant documents from one selected knowledge base
- Returns retrieval results as JSON so the agent can continue reasoning over them

## Design

This plugin is intentionally thin. It does not implement a new RAG backend. Instead, it wraps LangBot's built-in query-scoped knowledge retrieval APIs:

- `list_pipeline_knowledge_bases()` for enumerating KBs visible to the current query
- `retrieve_knowledge()` for retrieving top-k entries from a selected KB

The `query_id` is injected by the runtime when the tool is called, then stored inside `QueryBasedAPIProxy`. Because of that, the tool code only needs to pass business parameters such as `kb_id`, `query_text`, and `top_k`.

Although the underlying runtime can support metadata filters, this plugin does not expose raw filters to the agent in the current agentic tool flow. Different knowledge engines and vector backends may use different metadata fields, value formats, and filter semantics, and the agent currently has no reliable schema source for those fields.

Future versions may expose metadata filtering after the ecosystem has a more unified way to describe filterable fields and operators for each knowledge base.

## Security Boundary

This tool is scoped to the current pipeline.

- The plugin first lists the KBs visible to the current query and rejects KB IDs outside that set
- LangBot runtime also validates that the requested `kb_id` belongs to the current pipeline before executing retrieval

This means prompt injection alone should not allow the agent to query arbitrary KBs outside the pipeline configuration.

## How To Use

1. Install and enable the plugin.
2. Configure one or more knowledge bases in the current pipeline's local agent settings.
3. Let the agent call `query_knowledge`:
   - Start with `action="list"` to inspect available KBs
   - Then call `action="query"` with `kb_id`, `query_text`, and optional `top_k`

## Parameters

For `action="query"`, the tool currently accepts:

- `kb_id`: target knowledge base UUID
- `query_text`: retrieval query text
- `top_k`: optional positive integer, default `5`

## Typical Flow

1. Agent lists available KBs.
2. Agent selects one KB based on name and description.
3. Agent submits a focused retrieval query.
4. Agent uses the returned chunks to answer or continue tool use.
