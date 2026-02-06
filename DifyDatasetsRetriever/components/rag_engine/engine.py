from __future__ import annotations

import logging
from typing import Any

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


class DifyRAGEngine(RAGEngine):
    """RAG Engine powered by Dify Datasets.

    Dify datasets are managed externally via Dify's own interface.
    This engine only supports retrieval — document ingestion and deletion
    are not applicable.
    """

    @classmethod
    def get_capabilities(cls) -> list[str]:
        # No DOC_INGESTION: documents are managed in Dify, not via LangBot.
        return []

    # ========== Schema Definitions ==========

    def get_creation_settings_schema(self) -> list[dict[str, Any]]:
        """Return the schema for creating a Dify-backed Knowledge Base."""
        return [
            {
                "name": "api_base_url",
                "label": {
                    "en_US": "API Base URL",
                    "zh_Hans": "API 基础地址",
                },
                "description": {
                    "en_US": "The base URL of Dify API (e.g. https://api.dify.ai/v1)",
                    "zh_Hans": "Dify API 的基础地址 (例如 https://api.dify.ai/v1)",
                },
                "type": "string",
                "default": "https://api.dify.ai/v1",
                "required": True,
            },
            {
                "name": "dify_apikey",
                "label": {
                    "en_US": "API Key",
                    "zh_Hans": "API 密钥",
                },
                "description": {
                    "en_US": "Your Dify Dataset API Key",
                    "zh_Hans": "您的 Dify 知识库 API 密钥",
                },
                "type": "password",
                "required": True,
            },
            {
                "name": "dataset_id",
                "label": {
                    "en_US": "Dataset ID",
                    "zh_Hans": "数据集 ID",
                },
                "description": {
                    "en_US": "The UUID of the Dify Dataset to retrieve from",
                    "zh_Hans": "要检索的 Dify 数据集 UUID",
                },
                "type": "string",
                "required": True,
            },
            {
                "name": "search_method",
                "label": {
                    "en_US": "Search Method",
                    "zh_Hans": "检索模式",
                },
                "type": "select",
                "default": "keyword_search",
                "options": [
                    {"label": {"en_US": "Keyword Search", "zh_Hans": "关键词检索"}, "name": "keyword_search"},
                    {"label": {"en_US": "Semantic Search", "zh_Hans": "语义检索"}, "name": "semantic_search"},
                    {"label": {"en_US": "Hybrid Search", "zh_Hans": "混合检索"}, "name": "hybrid_search"},
                ],
                "required": False,
            },
            {
                "name": "score_threshold",
                "label": {
                    "en_US": "Score Threshold",
                    "zh_Hans": "分数阈值",
                },
                "type": "float",
                "default": 0.5,
                "required": False,
            },
        ]

    def get_retrieval_settings_schema(self) -> list[dict[str, Any]]:
        """Return schema for retrieval-time parameters."""
        return []

    # ========== Core Methods ==========

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Execute retrieval against Dify Dataset API."""
        config = context.creation_settings

        api_base_url = config.get("api_base_url", "https://api.dify.ai/v1").rstrip("/")
        api_key = config.get("dify_apikey")
        dataset_id = config.get("dataset_id")
        top_k = context.get_top_k()
        score_threshold = config.get("score_threshold", 0.5)
        search_method = config.get("search_method", "keyword_search")

        if not api_key or not dataset_id:
            logger.error(
                f"[DifyRAGEngine] Missing required configuration. "
                f"Config keys: {list(config.keys())}"
            )
            return RetrievalResponse(results=[], total_found=0)

        url = f"{api_base_url}/datasets/{dataset_id}/retrieve"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": context.query,
            "retrieval_model": {
                "search_method": search_method,
                "reranking_enable": False,
                "reranking_mode": None,
                "reranking_model": {
                    "reranking_provider_name": "",
                    "reranking_model_name": "",
                },
                "weights": None,
                "top_k": int(top_k),
                "score_threshold_enabled": True,
                "score_threshold": float(score_threshold),
            },
        }

        results: list[RetrievalResultEntry] = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                for record in data.get("records", []):
                    segment = record.get("segment", {})
                    document = segment.get("document", {})

                    score = record.get("score")
                    if score is None:
                        score = 0.0

                    results.append(
                        RetrievalResultEntry(
                            id=segment.get("id", ""),
                            content=[ContentElement.from_text(segment.get("content", ""))],
                            metadata={
                                "document_id": segment.get("document_id", ""),
                                "document_name": document.get("name", ""),
                                "segment_id": segment.get("id", ""),
                                "keywords": segment.get("keywords", []),
                                "answer": segment.get("answer"),
                            },
                            distance=1.0 - float(score),
                            score=float(score),
                        )
                    )

            logger.info(f"[DifyRAGEngine] Retrieved {len(results)} chunks from Dify.")
        except Exception:
            logger.exception("[DifyRAGEngine] Error during retrieval")

        return RetrievalResponse(results=results, total_found=len(results))

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """Dify datasets are managed externally; ingestion is not supported."""
        return IngestionResult(
            document_id=context.file_object.metadata.document_id,
            status=DocumentStatus.FAILED,
            error_message="Dify RAG engine does not support document ingestion. "
                          "Please manage documents directly in Dify.",
        )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """Dify datasets are managed externally; deletion is not supported."""
        logger.warning(
            f"[DifyRAGEngine] Document deletion not supported (doc={document_id}). "
            "Please manage documents directly in Dify."
        )
        return False

