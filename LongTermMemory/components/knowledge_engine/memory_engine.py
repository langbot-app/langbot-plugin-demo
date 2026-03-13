from __future__ import annotations

import json
import logging
import time
import uuid as uuid_mod
from typing import Any

from langbot_plugin.api.definition.components.knowledge_engine.engine import (
    KnowledgeEngine,
    KnowledgeEngineCapability,
)
from langbot_plugin.api.entities.builtin.rag.context import (
    RetrievalContext,
    RetrievalResponse,
    RetrievalResultEntry,
)
from langbot_plugin.api.entities.builtin.rag.models import (
    IngestionContext,
    IngestionResult,
)
from langbot_plugin.api.entities.builtin.rag.enums import DocumentStatus

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 32


class LongTermMemoryEngine(KnowledgeEngine):
    """Long-term memory KnowledgeEngine.

    Serves as the configuration entry point for the memory plugin
    (embedding model, isolation mode) and handles L2 episodic memory
    retrieval and import.
    """

    @classmethod
    def get_capabilities(cls) -> list[str]:
        return [KnowledgeEngineCapability.DOC_INGESTION]

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        existing = await self.plugin.memory_store.get_kb_configs()
        if existing:
            raise ValueError(
                "Only one memory knowledge base is supported per plugin instance. "
                "Please delete the existing one before creating a new one."
            )
        logger.info("Memory KB created: %s, config: %s", kb_id, config)
        await self.plugin.memory_store.save_kb_config(kb_id, config)

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        logger.info("Memory KB deleted: %s", kb_id)
        await self.plugin.memory_store.remove_kb_config(kb_id)

    # ================================================================
    # retrieve - called by LocalAgentRunner before LLM invocation
    # ================================================================

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        query = context.query
        collection_id = context.get_collection_id()
        settings = context.creation_settings
        retrieval_settings = context.retrieval_settings
        store = self.plugin.memory_store

        embedding_model_uuid = settings.get("embedding_model_uuid", "")
        top_k = retrieval_settings.get("top_k", settings.get("max_results", 5))

        if not query.strip() or not embedding_model_uuid:
            return RetrievalResponse(results=[], total_found=0)

        # embed the query
        query_vectors = await self.plugin.invoke_embedding(
            embedding_model_uuid, [query]
        )
        query_vector = query_vectors[0]

        session_name = retrieval_settings.get("session_name")
        sender_id = str(retrieval_settings.get("sender_id", "") or "")
        bot_uuid = str(retrieval_settings.get("bot_uuid", "") or "")
        isolation = settings.get("isolation", "session")
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        async def extend_results(filters: dict[str, Any] | None) -> None:
            nonlocal results
            batch = await self.plugin.vector_search(
                collection_id=collection_id,
                query_vector=query_vector,
                top_k=top_k,
                filters=filters,
            )
            for item in batch:
                item_id = item.get("id", "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                results.append(item)
                if len(results) >= top_k:
                    return

        if session_name:
            scope_key = store.get_scope_key_from_session_name(
                bot_uuid, session_name, isolation
            )

            if sender_id:
                await extend_results({"user_key": scope_key, "sender_id": sender_id})

            if len(results) < top_k:
                await extend_results({"user_key": scope_key})
        else:
            # Preserve previous broad-search behavior if session context is absent.
            await extend_results(None)

        results = results[:top_k]

        entries: list[RetrievalResultEntry] = []
        for r in results:
            meta = r.get("metadata", {})
            content = meta.get("content", "")
            timestamp = meta.get("timestamp", "")
            importance = meta.get("importance", "2")
            tags = meta.get("tags", "")

            display = f"[{timestamp}] (importance:{importance})"
            if tags:
                display += f" [{tags}]"
            display += f" {content}"

            entries.append(
                RetrievalResultEntry(
                    id=r.get("id", ""),
                    content=[{"type": "text", "text": display}],
                    metadata=meta,
                    score=r.get("score"),
                    distance=r.get("distance", 1.0 - r.get("score", 1.0)),
                )
            )

        return RetrievalResponse(results=entries, total_found=len(entries))

    # ================================================================
    # ingest - import memories from JSON file
    # ================================================================

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        doc_id = context.file_object.metadata.document_id
        filename = context.file_object.metadata.filename
        collection_id = context.get_collection_id()
        settings = context.creation_settings
        embedding_model_uuid = settings.get("embedding_model_uuid", "")

        logger.info("Ingesting memory file: %s (doc=%s)", filename, doc_id)

        if not embedding_model_uuid:
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message="No embedding model configured.",
            )

        # read file content
        try:
            content_bytes = await self.plugin.get_knowledge_file_stream(
                context.file_object.storage_path
            )
        except Exception as e:
            logger.error("Failed to read file: %s", e)
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=f"Could not read file: {e}",
            )

        # parse JSON array of memory entries
        try:
            text = content_bytes.decode("utf-8")

            # support pre-parsed content from a Parser plugin
            if context.parsed_content and context.parsed_content.text:
                text = context.parsed_content.text

            memories = json.loads(text)
            if not isinstance(memories, list):
                memories = [memories]
        except Exception as e:
            logger.error("Failed to parse memory file: %s", e)
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=f"Invalid JSON format: {e}",
            )

        if not memories:
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.COMPLETED,
                chunks_created=0,
            )

        # batch embed and upsert
        total_stored = 0
        batch_texts: list[str] = []
        batch_ids: list[str] = []
        batch_metas: list[dict[str, Any]] = []

        for mem in memories:
            content = mem.get("content", "")
            if not content:
                continue

            tags = mem.get("tags", [])
            importance = mem.get("importance", 2)
            timestamp = mem.get("timestamp", time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ))
            user_key = mem.get("user_key", "imported")

            mid = uuid_mod.uuid4().hex[:12]
            batch_texts.append(content)
            batch_ids.append(mid)
            batch_metas.append({
                "content": content,
                "tags": ",".join(tags) if isinstance(tags, list) else str(tags),
                "importance": str(importance),
                "timestamp": timestamp,
                "user_key": user_key,
                "source": "import",
                "document_id": doc_id,
            })

            if len(batch_texts) >= EMBEDDING_BATCH_SIZE:
                total_stored += await self._embed_and_upsert(
                    collection_id, embedding_model_uuid,
                    batch_texts, batch_ids, batch_metas,
                )
                batch_texts, batch_ids, batch_metas = [], [], []

        # flush remaining
        if batch_texts:
            total_stored += await self._embed_and_upsert(
                collection_id, embedding_model_uuid,
                batch_texts, batch_ids, batch_metas,
            )

        logger.info("Ingestion complete: %d memories stored", total_stored)
        return IngestionResult(
            document_id=doc_id,
            status=DocumentStatus.COMPLETED,
            chunks_created=total_stored,
        )

    async def _embed_and_upsert(
        self,
        collection_id: str,
        embedding_model_uuid: str,
        texts: list[str],
        ids: list[str],
        metas: list[dict[str, Any]],
    ) -> int:
        vectors = await self.plugin.invoke_embedding(embedding_model_uuid, texts)
        await self.plugin.vector_upsert(
            collection_id=collection_id,
            vectors=vectors,
            ids=ids,
            metadata=metas,
            documents=texts,
        )
        return len(texts)

    # ================================================================
    # delete_document - remove imported memories by document_id
    # ================================================================

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        count = await self.plugin.vector_delete(
            collection_id=kb_id,
            filters={"document_id": document_id},
        )
        return count > 0
