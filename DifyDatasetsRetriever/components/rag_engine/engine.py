
from __future__ import annotations

import logging
import httpx
import traceback
from typing import Any

from langbot_plugin.api.definition.components.rag_engine.engine import RAGEngine, RAGEngineCapability
from langbot_plugin.api.entities.builtin.rag.context import (
    RetrievalContext,
    RetrievalResultEntry,
    RetrievalResponse,
)
from langbot_plugin.api.entities.builtin.provider.message import ContentElement

logger = logging.getLogger(__name__)

class DifyRAGEngine(RAGEngine):
    """RAG Engine powered by Dify Datasets."""

    __kind__ = "RAGEngine"

    @classmethod
    def get_capabilities(cls) -> list[str]:
        # Since Dify datasets are managed externally via API/Key, 
        # we don't necessarily support "doc_ingestion" in the sense of uploading files via LangBot.
        # But if we want to allow users to use this as a searchable source, that's enough.
        # However, to be thorough, if we declare DOC_INGESTION, LangBot will show the upload UI.
        # Dify Datasets are usually read-only from this plugin's perspective (retriever).
        # We DO NOT support uploading documents to Dify via this plugin yet.
        return [] 

    def get_creation_settings_schema(self) -> list[dict[str, Any]]:
        """Return the schema for creating a Dify-backed Knowledge Base."""
        return [
                {
                    "name": "api_base_url",
                    "label": {
                        "en_US": "API Base URL",
                        "zh_Hans": "API 基础地址"
                    },
                    "description": {
                        "en_US": "The base URL of Dify API (e.g. https://api.dify.ai/v1)",
                        "zh_Hans": "Dify API 的基础地址 (例如 https://api.dify.ai/v1)"
                    },
                    "type": "string",
                    "default": "https://api.dify.ai/v1",
                    "required": True,
                },
                {
                    "name": "dify_apikey",
                    "label": {
                        "en_US": "API Key",
                        "zh_Hans": "API 密钥"
                    },
                    "description": {
                         "en_US": "Your Dify Dataset API Key",
                         "zh_Hans": "您的 Dify 知识库 API 密钥"
                    },
                    "type": "password",
                    "required": True,
                },
                {
                    "name": "dataset_id",
                    "label": {
                        "en_US": "Dataset ID",
                        "zh_Hans": "数据集 ID"
                    },
                    "description": {
                        "en_US": "The UUID of the Dify Dataset to retrieve from",
                        "zh_Hans": "要检索的 Dify 数据集 UUID"
                    },
                    "type": "string",
                    "required": True,
                },
                {
                    "name": "search_method",
                    "label": {
                        "en_US": "Search Method",
                        "zh_Hans": "检索模式"
                    },
                    "type": "select",
                    "default": "keyword_search",
                    "options": [
                        {
                            "label": {"en_US": "Keyword Search", "zh_Hans": "关键词检索"}, 
                            "name": "keyword_search"
                        },
                        {
                            "label": {"en_US": "Semantic Search", "zh_Hans": "语义检索"}, 
                            "name": "semantic_search"
                        },
                        {
                            "label": {"en_US": "Hybrid Search", "zh_Hans": "混合检索"}, 
                            "name": "hybrid_search"
                        },
                    ],
                    "required": False,
                },
                {
                    "name": "score_threshold",
                    "label": {
                        "en_US": "Score Threshold",
                        "zh_Hans": "分数阈值"
                    },
                    "type": "number",
                    "default": 0.5,
                    "required": False,
                }
            ]
    
    def get_retrieval_settings_schema(self) -> list[dict[str, Any]]:
        """Return schema for retrieval-time parameters (e.g. debug overrides)."""
        return []

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Execute retrieval against Dify."""
        
        # Get configuration from context.creation_settings as passed by the Host
        config = context.creation_settings
            
        api_base_url = config.get('api_base_url', 'https://api.dify.ai/v1').rstrip('/')
        api_key = config.get('dify_apikey')
        dataset_id = config.get('dataset_id')
        top_k = context.get_top_k()
        score_threshold = config.get('score_threshold', 0.5)
        search_method = config.get('search_method', 'keyword_search')

        if not api_key or not dataset_id:
             logger.error(f"[DifyRAGEngine] Missing required configuration. Config keys: {list(config.keys())}")
             # Return empty response instead of failing
             return RetrievalResponse(results=[], total_found=0)

        # Dify API Request
        url = f"{api_base_url}/datasets/{dataset_id}/retrieve"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "query": context.query,
            "retrieval_model": {
                "search_method": search_method,
                "reranking_enable": False,
                "reranking_mode": None,
                "reranking_model": {
                    "reranking_provider_name": "",
                    "reranking_model_name": ""
                },
                "weights": None,
                "top_k": int(top_k),
                "score_threshold_enabled": True,
                "score_threshold": float(score_threshold)
            }
        }
        
        results = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                data = response.json()
                
                for record in data.get('records', []):
                    segment = record.get('segment', {})
                    document = segment.get('document', {})
                    
                    score = record.get('score', 0.0)
                    if score is None: score = 0.5
                    
                    entry = RetrievalResultEntry(
                        id=segment.get('id', ''),
                        content=[ContentElement.from_text(segment.get('content', ''))],
                        metadata={
                            'document_id': segment.get('document_id', ''),
                            'document_name': document.get('name', ''),
                            'segment_id': segment.get('id', ''),
                            'keywords': segment.get('keywords', []),
                            'answer': segment.get('answer'),
                        },
                        distance=1.0 - float(score),
                        score=float(score)
                    )
                    results.append(entry)
                    
            logger.info(f"[DifyRAGEngine] Retrieved {len(results)} chunks from Dify.")
        except Exception as e:
            logger.error(f"[DifyRAGEngine] Error during retrieval: {e}")
            traceback.print_exc()
            
        return RetrievalResponse(
            results=results,
            total_found=len(results)
        )

    async def ingest(self, context: Any) -> Any:
        """Ingest a document into the knowledge base."""
        # Dify Datasets are read-only from this plugin's perspective.
        # We perform a no-op implementation to satisfy the interface.
        # Ideally we should return IngestionResult(success=True) or raise an error if called.
        return None

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """Delete a document from the knowledge base."""
        # Not supported
        return True

