from __future__ import annotations

import logging

import httpx

from langbot_plugin.api.definition.components.rag_engine import RAGEngine
from langbot_plugin.api.entities.builtin.rag import (
    IngestionContext,
    IngestionResult,
    DocumentStatus,
    RetrievalContext,
    RetrievalResultEntry,
    RetrievalResponse,
)
from langbot_plugin.api.entities.builtin.provider.message import ContentElement

logger = logging.getLogger(__name__)


class FastGPTRAGEngine(RAGEngine):
    """RAG Engine powered by FastGPT Datasets.

    FastGPT datasets are managed externally via FastGPT's own interface.
    This engine only supports retrieval — document ingestion and deletion
    are not applicable.
    """

    @classmethod
    def get_capabilities(cls) -> list[str]:
        return []

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Execute retrieval against FastGPT Dataset API."""
        config = context.creation_settings

        api_base_url = config.get("api_base_url", "http://localhost:3000").rstrip("/")
        api_key = config.get("api_key")
        dataset_id = config.get("dataset_id")
        limit = config.get("limit", 5000)
        similarity = config.get("similarity", 0.0)
        search_mode = config.get("search_mode", "embedding")
        using_rerank = config.get("using_rerank", False)
        dataset_search_using_extension_query = config.get("dataset_search_using_extension_query", False)
        dataset_search_extension_model = config.get("dataset_search_extension_model", "")
        dataset_search_extension_bg = config.get("dataset_search_extension_bg", "")

        if not api_key or not dataset_id:
            logger.error(
                f"[FastGPTRAGEngine] Missing required configuration. "
                f"Config keys: {list(config.keys())}"
            )
            return RetrievalResponse(results=[], total_found=0)

        url = f"{api_base_url}/api/core/dataset/searchTest"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "datasetId": dataset_id,
            "text": context.query,
            "limit": int(limit),
            "similarity": float(similarity),
            "searchMode": search_mode,
            "usingReRank": bool(using_rerank),
        }

        if dataset_search_using_extension_query:
            payload["datasetSearchUsingExtensionQuery"] = True
            if dataset_search_extension_model:
                payload["datasetSearchExtensionModel"] = dataset_search_extension_model
            if dataset_search_extension_bg:
                payload["datasetSearchExtensionBg"] = dataset_search_extension_bg

        results: list[RetrievalResultEntry] = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                response.raise_for_status()
                result = response.json()

                for record in result.get("data", []):
                    content_parts = []
                    if record.get("q"):
                        content_parts.append(record["q"])
                    if record.get("a"):
                        content_parts.append(record["a"])
                    content_text = "\n".join(content_parts) if content_parts else ""

                    score = record.get("score")
                    if score is None:
                        score = 0.0

                    results.append(
                        RetrievalResultEntry(
                            id=record.get("id", ""),
                            content=[ContentElement.from_text(content_text)],
                            metadata={
                                "dataset_id": record.get("datasetId", ""),
                                "collection_id": record.get("collectionId", ""),
                                "source_name": record.get("sourceName", ""),
                                "source_id": record.get("sourceId", ""),
                            },
                            distance=1.0 - float(score),
                            score=float(score),
                        )
                    )

            logger.info(f"[FastGPTRAGEngine] Retrieved {len(results)} chunks from FastGPT.")
        except Exception:
            logger.exception("[FastGPTRAGEngine] Error during retrieval")

        return RetrievalResponse(results=results, total_found=len(results))

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """FastGPT datasets are managed externally; ingestion is not supported."""
        return IngestionResult(
            document_id=context.file_object.metadata.document_id,
            status=DocumentStatus.FAILED,
            error_message="FastGPT RAG engine does not support document ingestion. "
                          "Please manage documents directly in FastGPT.",
        )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """FastGPT datasets are managed externally; deletion is not supported."""
        logger.warning(
            f"[FastGPTRAGEngine] Document deletion not supported (doc={document_id}). "
            "Please manage documents directly in FastGPT."
        )
        return False
