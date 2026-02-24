"""Abstract base class for index strategies."""

from abc import ABC, abstractmethod


class IndexStrategy(ABC):
    """Base class for RAG index strategies.

    Each strategy defines how documents are chunked/indexed during ingestion
    and how search results are post-processed during retrieval.
    """

    @abstractmethod
    def build_chunks_and_metadata(
        self,
        text: str,
        doc_id: str,
        filename: str,
        creation_settings: dict,
    ) -> tuple[list[str], list[str], list[dict]]:
        """Build chunks, IDs, and metadata for a parsed document.

        Args:
            text: Full parsed text of the document.
            doc_id: Unique document identifier.
            filename: Original filename.
            creation_settings: Knowledge base creation settings dict.

        Returns:
            A tuple of (texts_to_embed, ids, metadatas).
            - texts_to_embed: text chunks to be embedded.
            - ids: unique ID for each chunk.
            - metadatas: metadata dict for each chunk.
        """
        ...

    def postprocess_results(self, results: list[dict], top_k: int) -> list[dict]:
        """Post-process search results before returning to the caller.

        Default implementation is a no-op passthrough.

        Args:
            results: Raw search results from the vector store.
            top_k: Desired number of results.

        Returns:
            Processed results list.
        """
        return results[:top_k]
