# AgenticRAG

AgenticRAG exposes the knowledge bases configured for the current pipeline as an LLM Tool, so an agent can inspect available KBs and retrieve relevant chunks on demand.

## What It Does

- Provides a single tool, `query_knowledge`
- Supports two actions:
  - `list`: list knowledge bases available to the current pipeline
  - `query`: retrieve relevant documents from one or more selected knowledge bases
- Returns retrieval results as JSON so the agent can continue reasoning over them

## Design

This plugin is intentionally thin. It does not implement a new RAG backend. Instead, it wraps LangBot's built-in query-scoped knowledge retrieval APIs:

- `list_pipeline_knowledge_bases()` for enumerating KBs visible to the current query
- `retrieve_knowledge()` for retrieving top-k entries from one or more selected KBs

The `query_id` is injected by the runtime when the tool is called, then stored inside `QueryBasedAPIProxy`. Because of that, the tool code only needs to pass business parameters such as `kb_id` or `kb_ids`, `query_text`, and `top_k`.

Although the underlying runtime can support metadata filters, this plugin does not expose raw filters to the agent in the current agentic tool flow. Different knowledge engines and vector backends may use different metadata fields, value formats, and filter semantics, and the agent currently has no reliable schema source for those fields.

Future versions may expose metadata filtering after the ecosystem has a more unified way to describe filterable fields and operators for each knowledge base.

## Retrieval Behavior

When AgenticRAG is enabled, it disables the runner's automatic naive RAG pre-processing for the current pipeline.

- Retrieval is no longer performed automatically before the model answers
- Whether to query a knowledge base is now a deliberate model decision through `query_knowledge`
- If the model does not call the tool, no KB content will be injected into context

This reduces unconditional retrieval noise, but it also means tool prompting matters. The `query_knowledge` tool prompt is intentionally biased toward retrieval for factual, policy, procedural, product, and other domain-specific questions so the model prefers querying over guessing.

## Security Boundary

This tool is scoped to the current pipeline.

- LangBot runtime also validates that the requested `kb_id` belongs to the current pipeline before executing retrieval

This means prompt injection alone should not allow the agent to query arbitrary KBs outside the pipeline configuration.

## How To Use

1. Install and enable the plugin.
2. Configure one or more knowledge bases in the current pipeline's local agent settings.
3. Let the agent call `query_knowledge`:
   - Start with `action="list"` to inspect available KBs
   - Then call `action="query"` with either `kb_id` for one KB, or `kb_ids` for multiple KBs queried in parallel
   - Provide `query_text`, and optional `top_k` for the merged result count

## Parameters

For `action="query"`, the tool currently accepts:

- `kb_id`: target knowledge base UUID for single-KB retrieval
- `kb_ids`: optional array of target knowledge base UUIDs for parallel multi-KB retrieval
- `query_text`: retrieval query text
- `top_k`: optional positive integer, default `5`, applied to the merged result set

If one KB query fails while others succeed, the tool returns a JSON object with `results` and `failed_kbs` so the agent can continue with partial results.

## Typical Flow

1. Agent lists available KBs.
2. Agent selects one KB or a small set of KBs based on name and description.
3. Agent submits a focused retrieval query.
4. Agent uses the returned chunks to answer or continue tool use.

## Prompting Intent

The tool prompt is designed to communicate two things to the model:

- these knowledge bases are the authoritative source for in-scope information
- no fallback automatic retrieval exists once AgenticRAG is enabled

Without that guidance, an LLM may over-trust its pretrained knowledge and under-use retrieval. The current prompt therefore explicitly tells the model to query for uncertain or domain-specific questions and to prefer retrieval over unsupported recall.

## Logging

The plugin now emits logs during tool execution so you can observe how the LLM is using AgenticRAG in practice.

You will see logs for:

- tool call start, including `query_id`, `action`, and parameter keys
- KB listing start/end and how many KBs are visible
- retrieval start, including selected KBs, `top_k`, and a shortened `query_text` preview
- per-KB retrieval start/success/failure
- final retrieval summary, including merged result count, failed KB count, and returned result count

Typical log messages look like:

```text
[AgenticRAG] tool call started: query_id=123 action=query params_keys=['action', 'kb_id', 'query_text', 'top_k']
[AgenticRAG] retrieval requested: query_id=123 kb_ids=['kb-1'] kb_count=1 top_k=5 query='what is the refund policy'
[AgenticRAG] querying knowledge base: query_id=123 kb_id=kb-1 top_k=5
[AgenticRAG] knowledge base query succeeded: query_id=123 kb_id=kb-1 result_count=4
[AgenticRAG] retrieval completed: query_id=123 merged_results=4 failed_kbs=0
```
