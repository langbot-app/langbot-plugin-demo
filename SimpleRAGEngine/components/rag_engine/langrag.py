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
from .query_rewrite import retrieve_with_rewrite
from .strategies import get_strategy

logger = logging.getLogger(__name__)

# Batch size for embedding API calls.
# Stdio IPC is serial, so batches run sequentially — larger batches = fewer
# round-trips.  Keep under ~64 to avoid IPC response timeouts.
EMBEDDING_BATCH_SIZE = 32


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

            # 3. Build chunks via strategy
            index_type = context.creation_settings.get("index_type") or "chunk"
            strategy = get_strategy(index_type)
            logger.info(f"Strategy: {index_type} ({strategy.__class__.__name__})")

            texts_to_embed, ids, metadatas = strategy.build_chunks_and_metadata(
                text_content, doc_id, filename, context.creation_settings,
            )

            if texts_to_embed:
                logger.info(
                    f"Chunking result: {len(texts_to_embed)} chunks to embed, "
                    f"sample ID: {ids[0]}"
                )

            if not texts_to_embed:
                return IngestionResult(
                    document_id=doc_id,
                    status=DocumentStatus.COMPLETED,
                    chunks_created=0,
                )

            # 4. Embed and upsert in batches (stdio IPC is serial, no concurrency)
            embedding_model_uuid = context.creation_settings.get("embedding_model_uuid", "")
            total_stored = 0
            for i in range(0, len(texts_to_embed), EMBEDDING_BATCH_SIZE):
                batch_texts = texts_to_embed[i : i + EMBEDDING_BATCH_SIZE]
                batch_ids = ids[i : i + EMBEDDING_BATCH_SIZE]
                batch_metas = metadatas[i : i + EMBEDDING_BATCH_SIZE]

                batch_vectors = await self.plugin.invoke_embedding(
                    embedding_model_uuid, batch_texts,
                )
                await self.plugin.vector_upsert(
                    collection_id=collection_id,
                    vectors=batch_vectors,
                    ids=batch_ids,
                    metadata=batch_metas,
                    documents=batch_texts,
                )
                total_stored += len(batch_texts)

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

        # Determine strategy for post-processing
        index_type = context.creation_settings.get("index_type") or "chunk"
        strategy = get_strategy(index_type)
        logger.info(
            f"Retrieve: strategy={index_type}, top_k={top_k}, "
            f"query_rewrite={context.retrieval_settings.get('query_rewrite', 'off')}, "
            f"query={query!r}"
        )

        # For parent_child, over-fetch to allow dedup to still yield top_k results
        fetch_k = top_k * 3 if index_type == "parent_child" else top_k

        # Check query rewrite settings
        query_rewrite = context.retrieval_settings.get("query_rewrite", "off")
        rewrite_llm = context.creation_settings.get("rewrite_llm_model_uuid", "")

        if query_rewrite != "off" and rewrite_llm:
            logger.info(f"Query rewrite enabled: strategy={query_rewrite}")
            results = await retrieve_with_rewrite(
                plugin=self.plugin,
                query=query,
                query_rewrite=query_rewrite,
                rewrite_llm=rewrite_llm,
                collection_id=collection_id,
                embedding_model_uuid=context.creation_settings.get("embedding_model_uuid", ""),
                fetch_k=fetch_k,
                filters=context.filters or None,
                search_type=search_type,
            )
        else:
            # Original logic: embed query → vector_search
            query_vector: list[float] = []
            if search_type != SearchType.FULL_TEXT:
                embedding_model_uuid = context.creation_settings.get("embedding_model_uuid", "")
                query_vectors = await self.plugin.invoke_embedding(embedding_model_uuid, [query])
                query_vector = query_vectors[0]

            results = await self.plugin.vector_search(
                collection_id=collection_id,
                query_vector=query_vector,
                top_k=fetch_k,
                filters=context.filters or None,
                search_type=search_type,
                query_text=query,
            )

        # Post-process (strategy may deduplicate / re-rank)
        raw_count = len(results)
        results = strategy.postprocess_results(results, top_k)
        logger.info(
            f"Retrieve post-process: {raw_count} raw → {len(results)} after dedup "
            f"(fetch_k={fetch_k})"
        )

        # Format results
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
