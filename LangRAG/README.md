# LangRAG

RAG (Retrieval-Augmented Generation) Engine plugin for LangBot.

This plugin demonstrates how to build a Knowledge Engine that handles document ingestion and vector retrieval using LangBot Host's built-in infrastructure (Embedding models and Vector Database).

## Features

- **External Parser Integration** - Prefers pre-parsed content from a Parser plugin such as GeneralParsers, including structured sections and document metadata
- **Fallback Internal Parsing** - Includes a built-in parser as a fallback when no external parser is configured
- **Multiple Index Strategies** - Flat chunking, parent-child chunking, LLM-generated Q&A pairs
- **Flexible Retrieval** - Vector, full-text, or hybrid search
- **Query Rewriting** - HyDE, Multi-Query, Step-Back strategies for improved recall
- **Configurable Chunking** - Recursive character splitting with custom chunk size and overlap
- **Section-aware Chunking** - When structured sections are available, chunking preserves headings, page information, and table boundaries
- **Context Expansion** - Optionally appends adjacent chunks around each hit for richer retrieval context
- **Document Management** - Delete indexed vectors by document

## Architecture

```
┌─────────────────────────────────┐
│         LangBot Core            │
│  (Embedding / VDB / Storage)    │
└──────────┬──────────────────────┘
           │ RPC (IPC)
┌──────────▼──────────────────────┐
│          LangRAG                │
│  ┌───────────────────────────┐  │
│  │    Knowledge Engine       │  │
│  │  Parse → Chunk → Embed   │  │
│  │      → Store / Search    │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

## Ingestion Flow

LangRAG now prefers parser output provided by LangBot Host:

1. LangBot reads the uploaded file
2. A Parser plugin such as GeneralParsers extracts `text`, `sections`, and `metadata`
3. LangRAG ingests that structured result directly
4. If no parser output is available, LangRAG falls back to its internal parser
5. The selected index strategy builds chunks / Q&A pairs
6. LangBot Host generates embeddings and stores vectors

This means LangRAG works best when paired with an external parser plugin.

## Configuration

### Knowledge Base Creation

| Parameter | Description | Default |
|-----------|-------------|---------|
| `embedding_model_uuid` | Embedding model | Required |
| `index_type` | Index strategy: `chunk`, `parent_child`, or `qa` | `chunk` |
| `chunk_size` | Characters per chunk | 512 |
| `overlap` | Overlap between chunks | 50 |
| `parent_chunk_size` | Parent chunk size (parent_child only) | 2048 |
| `child_chunk_size` | Child chunk size (parent_child only) | 256 |
| `qa_llm_model_uuid` | LLM for Q&A generation (qa only) | - |
| `questions_per_chunk` | Questions to generate per chunk (qa only) | 1 |

### Retrieval

| Parameter | Description | Default |
|-----------|-------------|---------|
| `top_k` | Number of results to return | 5 |
| `search_type` | Search mode: `vector`, `full_text`, or `hybrid` | `vector` |
| `query_rewrite` | Rewrite strategy: `off`, `hyde`, `multi_query`, or `step_back` | `off` |
| `rewrite_llm_model_uuid` | LLM for query rewriting (when rewrite is enabled) | - |
| `context_window` | Number of adjacent chunks to append around each hit | 0 |

## Index Strategies

- **chunk** - Default flat chunking. Splits documents into fixed-size chunks and embeds each directly. When parser sections are available, chunks are created section-by-section instead of flattening the whole document.
- **parent_child** - Two-level chunking. Splits into large parent chunks, then smaller child chunks. Embeds child chunks but returns parent text for richer context. When parser sections are available, sections are used as natural parent boundaries.
- **qa** - LLM-generated Q&A pairs. Chunks text, uses an LLM to generate question-answer pairs per chunk, and embeds the questions. When parser sections are available, Q&A generation also becomes section-aware.

## Query Rewriting

- **hyde** - Hypothetical Document Embedding. Generates a hypothetical answer to the query, then embeds that answer for retrieval.
- **multi_query** - Generates 3 query variants, searches with each, and merges results by score.
- **step_back** - Generates a more abstract question and searches with both the original and abstract queries.

## Pairing With GeneralParsers

GeneralParsers is currently the recommended parser for LangRAG because it can provide:

- cleaner PDF extraction
- structured sections
- table-preserving text
- document-level metadata
- optional OCR and image descriptions via a vision model

LangRAG consumes those parser outputs directly during ingestion, which generally produces better chunks and better retrieval quality than the fallback parser.

## Development

```bash
pip install -r requirements.txt
cp .env.example .env
```

Configure `DEBUG_RUNTIME_WS_URL` and `PLUGIN_DEBUG_KEY` in `.env`, then launch with your IDE debugger.

## Links

- [LangBot Documentation](https://docs.langbot.app/)
