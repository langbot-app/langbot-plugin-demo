import logging

from langbot_plugin.api.definition.components.knowledge_engine import (
    KnowledgeEngine,
    KnowledgeEngineCapability,
)
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
# Larger batches = fewer round-trips.  Keep under ~64 to avoid IPC response
# timeouts.
EMBEDDING_BATCH_SIZE = 32


class LangRAG(KnowledgeEngine):
    """Simple Knowledge Engine implementation using Plugin IPC.

    Provides:
    - Document ingestion with parsing, chunking, embedding, and vector storage
    - Vector-based retrieval
    - Full integration with Host's embedding models and vector database
    """

    @classmethod
    def get_capabilities(cls) -> list[str]:
        """Declare supported capabilities."""
        return [
            KnowledgeEngineCapability.DOC_INGESTION,
            KnowledgeEngineCapability.DOC_PARSING,
        ]

    # ========== Lifecycle Hooks ==========

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        logger.info(f"Knowledge base created: {kb_id} with config: {config}")

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        logger.info(f"Knowledge base deleted: {kb_id}")

    # ========== Helpers ==========

    async def _embed_and_upsert(
        self,
        collection_id: str,
        embedding_model_uuid: str,
        texts: list[str],
        ids: list[str],
        metas: list[dict],
    ) -> int:
        """Embed a batch of texts and upsert into the vector store.

        Returns the number of vectors stored.
        """
        vectors = await self.plugin.invoke_embedding(embedding_model_uuid, texts)
        await self.plugin.vector_upsert(
            collection_id=collection_id,
            vectors=vectors,
            ids=ids,
            metadata=metas,
            documents=texts,
        )
        return len(texts)

    async def _expand_context(
        self,
        results: list[dict],
        collection_id: str,
        window: int,
    ) -> None:
        """Expand each result with adjacent chunks from the same document.

        For each hit, looks up chunks at chunk_index ± 1..window in the same
        document and appends their text to the result's metadata as
        ``context_before`` and ``context_after``.

        Requires the vector store to support ``vector_get_by_ids``.  If the
        method is unavailable or fails, this is a no-op.
        """
        get_by_ids = getattr(self.plugin, "vector_get_by_ids", None)
        if not callable(get_by_ids):
            return

        ids_to_fetch: set[str] = set()
        # Map result → adjacent IDs needed
        for res in results:
            meta = res.get("metadata", {})
            doc_id = meta.get("document_id", "")
            chunk_idx = meta.get("chunk_index")
            if doc_id and chunk_idx is not None:
                for offset in range(1, window + 1):
                    if chunk_idx - offset >= 0:
                        ids_to_fetch.add(f"{doc_id}_{chunk_idx - offset}")
                    ids_to_fetch.add(f"{doc_id}_{chunk_idx + offset}")

        if not ids_to_fetch:
            return

        adjacent = await get_by_ids(
            collection_id=collection_id, ids=list(ids_to_fetch)
        )
        # Build lookup: id → text
        adj_map: dict[str, str] = {}
        for item in adjacent:
            item_id = item.get("id", "")
            item_text = item.get("metadata", {}).get("text", "")
            if item_id and item_text:
                adj_map[item_id] = item_text

        # Attach context to results
        for res in results:
            meta = res.get("metadata", {})
            doc_id = meta.get("document_id", "")
            chunk_idx = meta.get("chunk_index")
            if doc_id and chunk_idx is not None:
                before_parts = []
                after_parts = []
                for offset in range(1, window + 1):
                    before_id = f"{doc_id}_{chunk_idx - offset}"
                    after_id = f"{doc_id}_{chunk_idx + offset}"
                    if before_id in adj_map:
                        before_parts.insert(0, adj_map[before_id])
                    if after_id in adj_map:
                        after_parts.append(adj_map[after_id])
                if before_parts:
                    meta["context_before"] = "\n".join(before_parts)
                if after_parts:
                    meta["context_after"] = "\n".join(after_parts)

    # ========== Core Methods ==========

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """Handle document ingestion: Read -> Parse -> Chunk -> Embed -> Store.

        Uses an async generator pipeline: the strategy yields batches
        incrementally, and each batch is embedded and upserted as soon as it
        is ready.  This ensures partial results are persisted early.
        """
        doc_id = context.file_object.metadata.document_id
        filename = context.file_object.metadata.filename
        collection_id = context.get_collection_id()

        logger.info(
            f"Ingesting file: {filename} (doc={doc_id}) into collection: {collection_id}"
        )

        # 1. Get file content from Host
        try:
            content_bytes = await self.plugin.get_knowledge_file_stream(
                context.file_object.storage_path
            )
        except Exception as e:
            logger.error(f"Failed to get file content: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=f"Could not read file: {e}",
            )

        try:
            # 2. Parse file content (prefer pre-parsed content from external Parser plugin)
            sections = None
            doc_metadata = None
            if context.parsed_content and context.parsed_content.text:
                text_content = context.parsed_content.text
                logger.info(
                    f"Using pre-parsed content from external parser for {filename}"
                )
                # Extract structured sections and metadata if available
                if context.parsed_content.sections:
                    sections = context.parsed_content.sections
                    logger.info(
                        f"Found {len(sections)} structured sections from parser"
                    )
                if context.parsed_content.metadata:
                    doc_metadata = context.parsed_content.metadata
                    logger.info(
                        f"Found document metadata from parser: "
                        f"{[k for k in doc_metadata if k != 'images']}"
                    )
            else:
                logger.warning(
                    f"No external parser content for {filename}; "
                    "falling back to internal FileParser. Consider configuring an "
                    "external parser (e.g. GeneralParsers) for better results."
                )
                parser = FileParser()
                text_content = await parser.parse(content_bytes, filename)

            if not text_content:
                logger.warning(f"No text content extracted from file: {filename}")
                return IngestionResult(
                    document_id=doc_id,
                    status=DocumentStatus.COMPLETED,
                    chunks_created=0,
                )

            # 3. Build chunks via strategy (async generator)
            index_type = context.creation_settings.get("index_type") or "chunk"
            strategy = get_strategy(index_type)
            embedding_model_uuid = context.creation_settings.get(
                "embedding_model_uuid", ""
            )
            logger.info(f"Strategy: {index_type} ({strategy.__class__.__name__})")

            # 4. Progressive ingest: consume generator → accumulate → embed+upsert
            #    when a full batch is ready.  Embedding happens between generator
            #    yields (sequential, not concurrent) to avoid IPC timeout issues.
            pending_texts: list[str] = []
            pending_ids: list[str] = []
            pending_metas: list[dict] = []
            total_stored = 0

            async for (
                batch_texts,
                batch_ids,
                batch_metas,
            ) in strategy.build_chunks_and_metadata(
                text_content,
                doc_id,
                filename,
                context.creation_settings,
                plugin=self.plugin,
                sections=sections,
                doc_metadata=doc_metadata,
            ):
                pending_texts.extend(batch_texts)
                pending_ids.extend(batch_ids)
                pending_metas.extend(batch_metas)

                # Flush full batches immediately
                while len(pending_texts) >= EMBEDDING_BATCH_SIZE:
                    t = pending_texts[:EMBEDDING_BATCH_SIZE]
                    i = pending_ids[:EMBEDDING_BATCH_SIZE]
                    m = pending_metas[:EMBEDDING_BATCH_SIZE]
                    pending_texts = pending_texts[EMBEDDING_BATCH_SIZE:]
                    pending_ids = pending_ids[EMBEDDING_BATCH_SIZE:]
                    pending_metas = pending_metas[EMBEDDING_BATCH_SIZE:]
                    total_stored += await self._embed_and_upsert(
                        collection_id,
                        embedding_model_uuid,
                        t,
                        i,
                        m,
                    )

            # Flush remaining
            if pending_texts:
                total_stored += await self._embed_and_upsert(
                    collection_id,
                    embedding_model_uuid,
                    pending_texts,
                    pending_ids,
                    pending_metas,
                )

            if total_stored:
                unit = "Q&A pairs" if index_type == "qa" else "chunks"
                logger.info(f"Ingestion complete: {total_stored} {unit} stored")

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
        fetch_k = top_k * 3 if index_type in ("parent_child", "qa") else top_k

        # Check query rewrite settings
        query_rewrite = context.retrieval_settings.get("query_rewrite", "off")
        rewrite_llm = context.retrieval_settings.get("rewrite_llm_model_uuid", "")

        if query_rewrite != "off" and rewrite_llm:
            logger.info(f"Query rewrite enabled: strategy={query_rewrite}")
            results = await retrieve_with_rewrite(
                plugin=self.plugin,
                query=query,
                query_rewrite=query_rewrite,
                rewrite_llm=rewrite_llm,
                collection_id=collection_id,
                embedding_model_uuid=context.creation_settings.get(
                    "embedding_model_uuid", ""
                ),
                fetch_k=fetch_k,
                filters=context.filters or None,
                search_type=search_type,
            )
        else:
            # Original logic: embed query → vector_search
            query_vector: list[float] = []
            if search_type != SearchType.FULL_TEXT:
                embedding_model_uuid = context.creation_settings.get(
                    "embedding_model_uuid", ""
                )
                query_vectors = await self.plugin.invoke_embedding(
                    embedding_model_uuid, [query]
                )
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

        # C1: Heading hit weighting — boost results whose heading_path
        # contains query keywords.  Each keyword hit multiplies the distance
        # by 0.9, improving the result's ranking.
        query_keywords = [w for w in query.lower().split() if len(w) >= 2]
        if query_keywords:
            for res in results:
                heading_path = (
                    res.get("metadata", {}).get("heading_path", "") or ""
                ).lower()
                if not heading_path:
                    continue
                distance = res.get("distance")
                if distance is not None and isinstance(distance, (int, float)):
                    for kw in query_keywords:
                        if kw in heading_path:
                            distance *= 0.9
                    res["distance"] = distance
            # Re-sort by distance (lower is better) after weighting
            results.sort(
                key=lambda r: (
                    r.get("distance")
                    if isinstance(r.get("distance"), (int, float))
                    else float("inf")
                )
            )

        # C2: Context window — attempt to fetch adjacent chunks from the same
        # document to provide surrounding context.  Only works when the vector
        # store supports ``vector_get_by_ids`` (gracefully skipped otherwise).
        context_window = context.retrieval_settings.get("context_window", 0)
        if context_window and context_window > 0:
            try:
                await self._expand_context(results, collection_id, context_window)
            except Exception as e:
                logger.debug(
                    f"Context window expansion skipped (vector_get_by_ids "
                    f"not supported or failed): {e}"
                )

        # Format results
        entries: list[RetrievalResultEntry] = []
        for res in results:
            meta = res.get("metadata", {})
            content_text = meta.get("text", "")
            raw_score = res.get("score")
            distance = res.get("distance")
            if distance is None and raw_score is not None:
                # Compatibility with older hosts that incorrectly returned
                # distance under the score field.
                distance = raw_score

            doc_name = meta.get("document_name", "")
            page = meta.get("page")
            heading_path = meta.get("heading_path", "")

            # Build structured reference string
            ref_parts = [doc_name]
            if page is not None:
                ref_parts.append(f"p.{page}")
            if heading_path:
                ref_parts.append(f'"{heading_path}"')
            reference = "[" + ", ".join(ref_parts) + "]" if ref_parts else ""

            content_entry: dict = {
                "type": "text",
                "text": content_text,
                "file_name": doc_name,
            }
            if page is not None:
                content_entry["page"] = page
            if heading_path:
                content_entry["heading_path"] = heading_path
            if reference:
                content_entry["reference"] = reference

            entries.append(
                RetrievalResultEntry(
                    id=res["id"],
                    content=[content_entry],
                    metadata=meta,
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
