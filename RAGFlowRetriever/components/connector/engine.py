from __future__ import annotations

import logging

import httpx

from langbot_plugin.api.definition.components.rag_engine import KnowledgeEngine, KnowledgeEngineCapability
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


class RAGFlowKnowledgeEngine(KnowledgeEngine):
    """RAG Engine powered by RAGFlow.

    Supports retrieval, document ingestion (upload + parse), and deletion
    via the RAGFlow HTTP API.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache knowledge-base configs keyed by kb_id for use in delete_document
        self._kb_configs: dict[str, dict] = {}

    @classmethod
    def get_capabilities(cls) -> list[str]:
        return [KnowledgeEngineCapability.DOC_INGESTION, KnowledgeEngineCapability.DOC_PARSING]

    # ========== Lifecycle Hooks ==========

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        """Cache knowledge-base configuration so delete_document can look it up."""
        logger.info(f"[RAGFlowKnowledgeEngine] Knowledge base created: {kb_id}")
        self._kb_configs[kb_id] = config

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        """Remove cached configuration for the deleted knowledge base."""
        logger.info(f"[RAGFlowKnowledgeEngine] Knowledge base deleted: {kb_id}")
        self._kb_configs.pop(kb_id, None)

    async def retrieve(self, context: RetrievalContext) -> RetrievalResponse:
        """Execute retrieval against RAGFlow API."""
        config = context.creation_settings
        retrieval = context.retrieval_settings

        api_base_url = config.get("api_base_url", "http://localhost:9380").rstrip("/")
        api_key = config.get("api_key")
        dataset_ids_str = config.get("dataset_ids", "")
        top_k = retrieval.get("top_k", 1024)
        similarity_threshold = retrieval.get("similarity_threshold", 0.2)
        vector_similarity_weight = retrieval.get("vector_similarity_weight", 0.3)
        page_size = retrieval.get("page_size", 30)
        keyword = retrieval.get("keyword", False)
        rerank_id = retrieval.get("rerank_id", "")
        use_kg = retrieval.get("use_kg", False)

        if not api_key or not dataset_ids_str:
            logger.error(
                f"[RAGFlowKnowledgeEngine] Missing required configuration. "
                f"Config keys: {list(config.keys())}"
            )
            return RetrievalResponse(results=[], total_found=0)

        dataset_ids = [did.strip() for did in dataset_ids_str.split(",") if did.strip()]

        if not dataset_ids:
            logger.error("[RAGFlowKnowledgeEngine] No valid dataset IDs provided")
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
            "keyword": keyword,
            "highlight": False,
            "use_kg": use_kg,
        }
        if rerank_id:
            payload["rerank_id"] = rerank_id

        results: list[RetrievalResultEntry] = []
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                if data.get("code") != 0:
                    logger.error(
                        f"[RAGFlowKnowledgeEngine] API returned error code: {data.get('code')}"
                    )
                    return RetrievalResponse(results=[], total_found=0)

                logger.info(
                    f"[RAGFlowKnowledgeEngine] Request: vector_weight={vector_similarity_weight}, "
                    f"top_k={top_k}, page_size={page_size}, threshold={similarity_threshold}, "
                    f"keyword={keyword}, rerank_id={rerank_id or 'None'}, use_kg={use_kg}, "
                    f"Response chunks: {len(data.get('data', {}).get('chunks', []))}"
                )

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

            logger.info(f"[RAGFlowKnowledgeEngine] Retrieved {len(results)} chunks from RAGFlow.")
        except Exception:
            logger.exception("[RAGFlowKnowledgeEngine] Error during retrieval")

        return RetrievalResponse(results=results, total_found=len(results))

    async def ingest(self, context: IngestionContext) -> IngestionResult:
        """Upload a file to RAGFlow and trigger parsing."""
        doc_id = context.file_object.metadata.document_id
        filename = context.file_object.metadata.filename

        config = context.creation_settings
        api_base_url = config.get("api_base_url", "http://localhost:9380").rstrip("/")
        api_key = config.get("api_key")
        dataset_ids_str = config.get("dataset_ids", "")

        if not api_key or not dataset_ids_str:
            logger.error(
                f"[RAGFlowKnowledgeEngine] Missing required configuration for ingestion. "
                f"Config keys: {list(config.keys())}"
            )
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message="Missing api_key or dataset_ids in configuration.",
            )

        dataset_ids = [did.strip() for did in dataset_ids_str.split(",") if did.strip()]
        if not dataset_ids:
            logger.error("[RAGFlowKnowledgeEngine] No valid dataset IDs provided for ingestion")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message="No valid dataset IDs provided.",
            )

        # Use the first dataset as the ingestion target
        target_dataset_id = dataset_ids[0]

        # 1. Read file content from Host
        try:
            file_bytes = await self.plugin.get_rag_file_stream(context.file_object.storage_path)
        except Exception as e:
            logger.error(f"[RAGFlowKnowledgeEngine] Failed to get file content: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=f"Could not read file: {e}",
            )

        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient() as client:
                # 2. Upload file to RAGFlow dataset
                upload_url = f"{api_base_url}/api/v1/datasets/{target_dataset_id}/documents"
                files = {"file": (filename, file_bytes)}
                upload_resp = await client.post(
                    upload_url, headers=headers, files=files, timeout=60.0
                )
                upload_resp.raise_for_status()
                upload_data = upload_resp.json()

                if upload_data.get("code") != 0:
                    error_msg = upload_data.get("message", "Unknown upload error")
                    logger.error(f"[RAGFlowKnowledgeEngine] Upload failed: {error_msg}")
                    return IngestionResult(
                        document_id=doc_id,
                        status=DocumentStatus.FAILED,
                        error_message=f"RAGFlow upload error: {error_msg}",
                    )

                # Extract the document ID returned by RAGFlow
                docs = upload_data.get("data", [])
                if not docs:
                    logger.error("[RAGFlowKnowledgeEngine] Upload returned no document data")
                    return IngestionResult(
                        document_id=doc_id,
                        status=DocumentStatus.FAILED,
                        error_message="RAGFlow upload returned empty document list.",
                    )

                ragflow_doc_id = docs[0].get("id", doc_id)

                # 3. Trigger parsing
                chunks_url = f"{api_base_url}/api/v1/datasets/{target_dataset_id}/chunks"
                parse_resp = await client.post(
                    chunks_url,
                    headers={**headers, "Content-Type": "application/json"},
                    json={"document_ids": [ragflow_doc_id]},
                    timeout=30.0,
                )
                parse_resp.raise_for_status()
                parse_data = parse_resp.json()

                if parse_data.get("code") != 0:
                    error_msg = parse_data.get("message", "Unknown parsing error")
                    logger.warning(
                        f"[RAGFlowKnowledgeEngine] Parsing trigger returned error: {error_msg}"
                    )
                    # Document was uploaded but parsing failed to start
                    return IngestionResult(
                        document_id=ragflow_doc_id,
                        status=DocumentStatus.FAILED,
                        error_message=f"RAGFlow parsing trigger error: {error_msg}",
                    )

                logger.info(
                    f"[RAGFlowKnowledgeEngine] File '{filename}' uploaded and parsing triggered "
                    f"(ragflow_doc_id={ragflow_doc_id})"
                )

                return IngestionResult(
                    document_id=ragflow_doc_id,
                    status=DocumentStatus.PROCESSING,
                )

        except Exception as e:
            logger.error(f"[RAGFlowKnowledgeEngine] Ingestion failed for {filename}: {e}")
            return IngestionResult(
                document_id=doc_id,
                status=DocumentStatus.FAILED,
                error_message=str(e),
            )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        """Delete a document from RAGFlow."""
        config = self._kb_configs.get(kb_id)
        if not config:
            logger.error(
                f"[RAGFlowKnowledgeEngine] No cached config for kb_id={kb_id}, "
                "cannot delete document"
            )
            return False

        api_base_url = config.get("api_base_url", "http://localhost:9380").rstrip("/")
        api_key = config.get("api_key")
        dataset_ids_str = config.get("dataset_ids", "")

        if not api_key or not dataset_ids_str:
            logger.error(
                f"[RAGFlowKnowledgeEngine] Missing api_key or dataset_ids for kb_id={kb_id}"
            )
            return False

        dataset_ids = [did.strip() for did in dataset_ids_str.split(",") if did.strip()]
        if not dataset_ids:
            logger.error(
                f"[RAGFlowKnowledgeEngine] No valid dataset IDs for kb_id={kb_id}"
            )
            return False

        target_dataset_id = dataset_ids[0]

        try:
            async with httpx.AsyncClient() as client:
                url = f"{api_base_url}/api/v1/datasets/{target_dataset_id}/documents"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                resp = await client.request(
                    "DELETE", url, headers=headers,
                    json={"ids": [document_id]},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    error_msg = data.get("message", "Unknown error")
                    logger.error(
                        f"[RAGFlowKnowledgeEngine] Delete failed for doc={document_id}: {error_msg}"
                    )
                    return False

                logger.info(
                    f"[RAGFlowKnowledgeEngine] Document {document_id} deleted from "
                    f"dataset {target_dataset_id}"
                )
                return True

        except Exception:
            logger.exception(
                f"[RAGFlowKnowledgeEngine] Error deleting document {document_id}"
            )
            return False
