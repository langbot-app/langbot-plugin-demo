import logging

from langbot_plugin.api.definition.components.rag_engine import RAGEngine, RAGEngineCapability
from langbot_plugin.api.entities.builtin.rag import (
    IngestionContext,
    IngestionResult,
    RetrievalContext,
    RetrievalResponse,
    RetrievalResultEntry,
    DocumentStatus,
    SearchType,
)

from .parser import FileParser

logger = logging.getLogger(__name__)

# Default chunking parameters
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50
# Batch size for embedding API calls to avoid IPC timeouts
EMBEDDING_BATCH_SIZE = 10


# Separators in order of semantic significance (paragraph → sentence → word → char)
_SEPARATORS = [
    "\n\n",  # Paragraphs
    "\n",    # Lines
    ". ",    # Sentences
    "。",    # Chinese/Japanese sentence end
    "! ",    # Exclamations
    "? ",    # Questions
    "; ",    # Semicolons
    "；",    # Chinese semicolon
    "，",    # Chinese comma
    ", ",    # Commas
    " ",     # Spaces (words)
    "",      # Characters (fallback)
]


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into overlapping chunks using recursive character splitting.

    Attempts to split at natural semantic boundaries (paragraphs, sentences,
    words) before falling back to character-level splitting. This preserves
    readability and context compared to a naive sliding-window approach.

    Args:
        text: The text to split.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        List of text chunks.
    """
    if not text:
        return []

    if chunk_overlap >= chunk_size:
        logger.warning(
            f"chunk_overlap ({chunk_overlap}) >= chunk_size ({chunk_size}), "
            "clamping overlap to chunk_size - 1"
        )
        chunk_overlap = chunk_size - 1

    return _split_recursive(text, _SEPARATORS, chunk_size, chunk_overlap)


def _split_recursive(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Recursively split *text* trying each separator in priority order."""
    final_chunks: list[str] = []
    separator = separators[0] if separators else ""
    remaining_separators = separators[1:] if len(separators) > 1 else []

    splits = _split_by_separator(text, separator)

    current_parts: list[str] = []
    current_len = 0

    for part in splits:
        part_len = len(part)

        # Single piece already exceeds limit → recurse with finer separator
        if part_len > chunk_size:
            # Flush accumulated parts first
            if current_parts:
                final_chunks.append("".join(current_parts))
                current_parts = _overlap_parts(current_parts, chunk_overlap)
                current_len = sum(len(p) for p in current_parts)

            if remaining_separators:
                final_chunks.extend(
                    _split_recursive(part, remaining_separators, chunk_size, chunk_overlap)
                )
            else:
                final_chunks.extend(_split_by_char(part, chunk_size, chunk_overlap))
            continue

        # Would adding this part exceed the limit?
        if current_parts and current_len + part_len > chunk_size:
            final_chunks.append("".join(current_parts))
            current_parts = _overlap_parts(current_parts, chunk_overlap)
            current_len = sum(len(p) for p in current_parts)

        current_parts.append(part)
        current_len += part_len

    if current_parts:
        final_chunks.append("".join(current_parts))

    return final_chunks


def _split_by_separator(text: str, separator: str) -> list[str]:
    """Split *text* by *separator*, keeping the separator attached to the left piece."""
    if separator == "":
        return list(text)

    parts = text.split(separator)
    result: list[str] = []
    for piece in parts[:-1]:
        if piece or separator.strip():
            result.append(piece + separator)
    if parts[-1]:
        result.append(parts[-1])
    return result


def _overlap_parts(parts: list[str], overlap: int) -> list[str]:
    """Return trailing *parts* whose combined length fits within *overlap*."""
    if overlap <= 0:
        return []

    kept: list[str] = []
    total = 0
    for part in reversed(parts):
        if total + len(part) > overlap:
            break
        kept.insert(0, part)
        total += len(part)
    return kept


def _split_by_char(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Last-resort character-level split."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += chunk_size - overlap
    return chunks


class LangRAG(RAGEngine):
    """Simple RAG Engine implementation using Plugin IPC.

    Provides:
    - Document ingestion with parsing, chunking, embedding, and vector storage
    - Vector-based retrieval
    - Full integration with Host's embedding models and vector database
    """

    @classmethod
    def get_capabilities(cls) -> list[str]:
        """Declare supported capabilities."""
        return [RAGEngineCapability.DOC_INGESTION]

    # ========== Lifecycle Hooks ==========

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        logger.info(f"Knowledge base created: {kb_id} with config: {config}")

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        logger.info(f"Knowledge base deleted: {kb_id}")

    # ========== Core Methods ==========

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """Handle document ingestion: Read -> Parse -> Chunk -> Embed -> Store."""
        doc_id = context.file_object.metadata.document_id
        filename = context.file_object.metadata.filename
        collection_id = context.get_collection_id()

        logger.info(f"Ingesting file: {filename} (doc={doc_id}) into collection: {collection_id}")

        # 1. Get file content from Host
        try:
            content_bytes = await self.plugin.get_rag_file_stream(context.file_object.storage_path)
        except Exception as e:
            logger.error(f"Failed to get file content: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=f"Could not read file: {e}",
            )

        try:
            # 2. Parse file content
            parser = FileParser()
            text_content = await parser.parse(content_bytes, filename)

            if not text_content:
                logger.warning(f"No text content extracted from file: {filename}")
                return IngestionResult(
                    document_id=doc_id,
                    status=DocumentStatus.COMPLETED,
                    chunks_created=0,
                )

            # 3. Chunk with overlap
            chunk_size = context.creation_settings.get("chunk_size") or DEFAULT_CHUNK_SIZE
            chunk_overlap = context.creation_settings.get("overlap") or DEFAULT_CHUNK_OVERLAP
            chunks = _chunk_text(text_content, chunk_size, chunk_overlap)

            if not chunks:
                return IngestionResult(
                    document_id=doc_id,
                    status=DocumentStatus.COMPLETED,
                    chunks_created=0,
                )

            # 4. Embed and upsert in batches to avoid IPC timeouts
            embedding_model_uuid = context.creation_settings.get("embedding_model_uuid", "")
            total_stored = 0
            for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
                batch_chunks = chunks[i : i + EMBEDDING_BATCH_SIZE]
                batch_vectors = await self.plugin.invoke_embedding(embedding_model_uuid, batch_chunks)

                batch_ids = [f"{doc_id}_{i + j}" for j in range(len(batch_chunks))]
                batch_metadatas = [
                    {
                        "file_id": doc_id,
                        "document_id": doc_id,
                        "document_name": filename,
                        "chunk_index": i + j,
                        "text": chunk,
                    }
                    for j, chunk in enumerate(batch_chunks)
                ]

                await self.plugin.vector_upsert(
                    collection_id=collection_id,
                    vectors=batch_vectors,
                    ids=batch_ids,
                    metadata=batch_metadatas,
                    documents=batch_chunks,
                )
                total_stored += len(batch_chunks)

            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.COMPLETED,
                chunks_created=total_stored,
            )

        except Exception as e:
            logger.error(f"Ingestion failed for {filename}: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=str(e),
            )

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Retrieve relevant content with support for vector, full-text, and hybrid search."""
        query = context.query
        top_k = context.retrieval_settings.get("top_k", 5)
        collection_id = context.get_collection_id()
        search_type = context.retrieval_settings.get("search_type", SearchType.VECTOR)

        # 1. Embed query (skip for pure full-text search)
        query_vector: list[float] = []
        if search_type != SearchType.FULL_TEXT:
            embedding_model_uuid = context.creation_settings.get("embedding_model_uuid", "")
            query_vectors = await self.plugin.invoke_embedding(embedding_model_uuid, [query])
            query_vector = query_vectors[0]

        # 2. Search
        results = await self.plugin.vector_search(
            collection_id=collection_id,
            query_vector=query_vector,
            top_k=top_k,
            filters=context.filters or None,
            search_type=search_type,
            query_text=query,
        )

        # 3. Format results
        entries: list[RetrievalResultEntry] = []
        for res in results:
            content_text = res.get("metadata", {}).get("text", "")
            raw_score = res.get("score")
            distance = res.get("distance", raw_score)

            entries.append(
                RetrievalResultEntry(
                    id=res["id"],
                    content=[{"type": "text", "text": content_text}],
                    metadata=res.get("metadata", {}),
                    score=raw_score,
                    distance=distance,
                )
            )

        return RetrievalResponse(results=entries, total_found=len(entries))

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """Delete a document's vectors by file_id."""
        count = await self.plugin.vector_delete(
            collection_id=kb_id,
            file_ids=[document_id],
        )
        return count > 0
