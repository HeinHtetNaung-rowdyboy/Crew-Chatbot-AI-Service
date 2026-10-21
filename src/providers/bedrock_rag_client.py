
import asyncio
import logging
import time
from typing import Any

from src.prompts.generation_prompt import GENERATION_PROMPT

logger = logging.getLogger(__name__)


class BedrockRagError(Exception):
    """Raised when Bedrock RetrieveAndGenerate fails."""


class BedrockRagClient:
    """Generate grounded answers using an Amazon Bedrock Knowledge Base."""

    def __init__(
        self,
        client,
        knowledge_base_id: str,
        model_arn: str,
    ):
        self.client = client
        self.knowledge_base_id = knowledge_base_id
        self.model_arn = model_arn

    async def ask(self, question: str) -> dict[str, Any]:
        """Generate an answer without passing an application conversation ID.

        Bedrock-managed conversation continuity is intentionally not enabled
        here. The application conversation ID is managed separately by Redis.
        """
        if not self.knowledge_base_id or not self.model_arn:
            raise BedrockRagError(
                "KNOWLEDGE_BASE_ID or MODEL_ARN is not configured."
            )

        request = {
            "input": {
                "text": question,
            },
            "retrieveAndGenerateConfiguration": {
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": self.knowledge_base_id,
                    "modelArn": self.model_arn,
                    "generationConfiguration": {
                        "promptTemplate": {
                            "textPromptTemplate": GENERATION_PROMPT,
                        },
                    },
                },
            },
        }

        started = time.perf_counter()

        try:
            response = await asyncio.to_thread(
                self.client.retrieve_and_generate,
                **request,
            )
        except Exception as exc:
            logger.exception("Bedrock RetrieveAndGenerate failed")
            raise BedrockRagError(
                "The AI service could not process the request."
            ) from exc

        return {
            "response": response,
            "latency": time.perf_counter() - started,
        }


def extract_citations(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract retrieved references from a Bedrock response."""
    citations: list[dict[str, Any]] = []

    for citation in response.get("citations", []):
        generated = citation.get("generatedResponsePart", {})
        text_part = generated.get("textResponsePart", {})
        generated_text = text_part.get("text", "")

        for reference in citation.get("retrievedReferences", []):
            citations.append(
                {
                    "text": generated_text,
                    "content": reference.get("content", {}).get("text", ""),
                    "location": reference.get("location", {}),
                    "metadata": reference.get("metadata", {}),
                    "source_name": get_source_name(reference),
                }
            )

    return citations


def get_source_name(reference: dict[str, Any]) -> str:
    """Resolve a human-readable source name from a retrieved reference."""
    location = reference.get("location", {})

    s3_uri = location.get("s3Location", {}).get("uri")
    if s3_uri:
        return s3_uri.rstrip("/").split("/")[-1]

    metadata = reference.get("metadata", {})
    for key in (
        "fileName",
        "filename",
        "source",
        "document_name",
        "documentName",
        "title",
    ):
        value = metadata.get(key)
        if value:
            return str(value)

    web_location = location.get("webLocation", {}).get("url")
    if web_location:
        return str(web_location)

    return "Document"
