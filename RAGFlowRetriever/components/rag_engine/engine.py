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


class RAGFlowRAGEngine(RAGEngine):
    """RAG Engine powered by RAGFlow.

    RAGFlow datasets are managed externally via RAGFlow's own interface.
    This engine only supports retrieval — document ingestion and deletion
    are not applicable.
    """

    @classmethod
    def get_capabilities(cls) -> list[str]:
        return []

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Execute retrieval against RAGFlow API."""
        config = context.creation_settings

        api_base_url = config.get("api_base_url", "http://localhost:9380").rstrip("/")
        api_key = config.get("api_key")
        dataset_ids_str = config.get("dataset_ids", "")
        top_k = config.get("top_k", 1024)
        similarity_threshold = config.get("similarity_threshold", 0.2)
        vector_similarity_weight = config.get("vector_similarity_weight", 0.3)
        page_size = config.get("page_size", 30)

        if not api_key or not dataset_ids_str:
            logger.error(
                f"[RAGFlowRAGEngine] Missing required configuration. "
                f"Config keys: {list(config.keys())}"
            )
            return RetrievalResponse(results=[], total_found=0)

        dataset_ids = [did.strip() for did in dataset_ids_str.split(",") if did.strip()]

        if not dataset_ids:
            logger.error("[RAGFlowRAGEngine] No valid dataset IDs provided")
            return RetrievalResponse(results=[], total_found=0)

        url = f"{api_base_url}/api/v1/retrieval"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "question": context.query,
            "dataset_ids": dataset_ids,
            "page": 1,
            "page_size": int(page_size),
            "similarity_threshold": float(similarity_threshold),
            "vector_similarity_weight": float(vector_similarity_weight),
            "top_k": int(top_k),
            "keyword": False,
            "highlight": False,
        }

        results: list[RetrievalResultEntry] = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                if data.get("code") != 0:
                    logger.error(
                        f"[RAGFlowRAGEngine] API returned error code: {data.get('code')}"
                    )
                    return RetrievalResponse(results=[], total_found=0)

                for chunk in data.get("data", {}).get("chunks", []):
                    similarity = chunk.get("similarity")
                    if similarity is None:
                        similarity = 0.0

                    results.append(
                        RetrievalResultEntry(
                            id=chunk.get("id", ""),
                            content=[ContentElement.from_text(chunk.get("content", ""))],
                            metadata={
                                "document_id": chunk.get("document_id", ""),
                                "kb_id": chunk.get("kb_id", ""),
                                "document_keyword": chunk.get("document_keyword", ""),
                                "important_keywords": chunk.get("important_keywords", []),
                                "term_similarity": chunk.get("term_similarity", 0.0),
                                "vector_similarity": chunk.get("vector_similarity", 0.0),
                                "image_id": chunk.get("image_id"),
                            },
                            distance=1.0 - float(similarity),
                            score=float(similarity),
                        )
                    )

            logger.info(f"[RAGFlowRAGEngine] Retrieved {len(results)} chunks from RAGFlow.")
        except Exception:
            logger.exception("[RAGFlowRAGEngine] Error during retrieval")

        return RetrievalResponse(results=results, total_found=len(results))

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """RAGFlow datasets are managed externally; ingestion is not supported."""
        return IngestionResult(
            document_id=context.file_object.metadata.document_id,
            status=DocumentStatus.FAILED,
            error_message="RAGFlow RAG engine does not support document ingestion. "
                          "Please manage documents directly in RAGFlow.",
        )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """RAGFlow datasets are managed externally; deletion is not supported."""
        logger.warning(
            f"[RAGFlowRAGEngine] Document deletion not supported (doc={document_id}). "
            "Please manage documents directly in RAGFlow."
        )
        return False
