import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeBaseError(Exception):
    """Raised when Bedrock Knowledge Bases retrieval fails."""


class KnowledgeBaseRetriever:
    """Retrieve raw passages using bedrock-agent-runtime.retrieve.

    This class intentionally does not call retrieve_and_generate or a
    foundation model, so the returned passage text is not rewritten.
    """

    def __init__(
        self,
        client,
        knowledge_base_id: str,
        number_of_results: int = 5,
    ):
        self.client = client
        self.knowledge_base_id = knowledge_base_id
        self.number_of_results = number_of_results

    async def retrieve(self, query: str) -> list[dict[str, Any]]:
        if not self.knowledge_base_id:
            raise KnowledgeBaseError("KNOWLEDGE_BASE_ID is not configured")
        if not query or not query.strip():
            return []

        try:
            response = await asyncio.to_thread(
                self.client.retrieve,
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query.strip()},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": self.number_of_results
                    }
                },
            )
        except Exception as exc:
            logger.exception("Bedrock Knowledge Bases retrieve call failed")
            raise KnowledgeBaseError(
                "Knowledge retrieval is temporarily unavailable"
            ) from exc

        output: list[dict[str, Any]] = []
        for item in response.get("retrievalResults", []):
            content = item.get("content") or {}
            text = content.get("text")
            if not isinstance(text, str) or not text.strip():
                continue

            location = item.get("location") or {}
            s3_location = location.get("s3Location") or {}
            web_location = location.get("webLocation") or {}
            metadata = item.get("metadata") or {}

            source_uri = (
                s3_location.get("uri")
                or web_location.get("url")
                or metadata.get("source_uri")
                or metadata.get("source")
            )
            title = (
                metadata.get("title")
                or metadata.get("document_title")
                or metadata.get("documentName")
                or metadata.get("fileName")
                or (source_uri.rsplit("/", 1)[-1] if source_uri else None)
            )

            output.append({
                "text": text,
                "score": item.get("score"),
                "source_uri": source_uri,
                "title": title,
                "location": metadata.get("page")
                    or metadata.get("section")
                    or metadata.get("chapter"),
                "metadata": metadata,
            })
        return output
