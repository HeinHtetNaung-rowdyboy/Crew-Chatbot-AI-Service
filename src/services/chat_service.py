import json
import logging
import re
import time
from typing import Any

from fastapi import status

from src.providers.bedrock_rag_client import (
    BedrockRagClient,
    BedrockRagError,
    extract_citations,
)
from src.providers.bedrock_tool_client import (
    BedrockToolClient,
    BedrockToolError,
)
from src.retrieval.knowledge_base import (
    KnowledgeBaseError,
    KnowledgeBaseRetriever,
)
from src.schemas.chat_response import ChatResponse, Citation


logger = logging.getLogger(__name__)


class ChatServiceError(Exception):
    def __init__(self, public_message: str, status_code: int = 503):
        self.public_message = public_message
        self.status_code = status_code
        super().__init__(public_message)


class ChatService:
    """Route document questions to Bedrock and live-data requests to Java / MarineOn."""

    def __init__(
        self,
        settings,
        store,
        retriever: KnowledgeBaseRetriever,
        tool_client: BedrockToolClient | None = None,
        rag_client: BedrockRagClient | None = None,
    ):
        self.settings = settings
        self.store = store
        self.retriever = retriever
        self.tool_client = tool_client
        self.rag_client = rag_client

        logger.info(
            "ChatService initialized | retriever_available=%s "
            "rag_client_available=%s tool_client_available=%s",
            self.retriever is not None,
            self.rag_client is not None,
            self.tool_client is not None,
        )

    @staticmethod
    def _select_route(message: str) -> dict[str, Any]:
        """Route document questions and explicit live-data requests."""
        text = message.casefold()

        asks_documents = bool(
            re.search(
                r"\b("
                r"according to|procedure|procedures|policy|policies|"
                r"requirements?|regulation|regulations|"
                r"what does|what do|what happens|why|explain|"
                r"how should|how must|under what conditions|"
                r"repatriation|recruitment|manning|wages|"
                r"employment|seafarer|justifiable reason|"
                r"contract clause|rest hours|working hours|"
                r"rules?|process|entitlement|obligation|"
                r"leave|disciplinary|repatriate|minimum age|"
                r"can (?:he|she|they|this person)|eligible|"
                r"join the ship|join (?:a|the) ship"
                r")\b",
                text,
            )
        )

        asks_live_data = bool(
            re.search(
                r"\b("
                r"list|show|display|fetch|retrieve|find|"
                r"how many|count|which|all records|database|"
                r"live data|current status|status of|"
                r"currently assigned|currently onboard|"
                r"from the system"
                r")\b",
                text,
            )
        )

        asks_certificate = bool(
            re.search(
                r"\b(certificates?|certifications?|stcw|coc|coe)\b",
                text,
            )
        )
        asks_contract = bool(
            re.search(
                r"\b(contracts?|employment agreements?)\b",
                text,
            )
        )
        asks_vessel = bool(
            re.search(r"\b(vessels?|ships?|fleet)\b", text)
        )
        asks_expiry = bool(
            re.search(
                r"\b(expir\w*|expiry|expiration|expired|overdue|due|renewal|renewals)\b",
                text,
            )
        )

        tool_name = None

        if asks_live_data and asks_contract and asks_expiry:
            tool_name = "get_expired_contracts"
        elif asks_live_data and asks_certificate and asks_expiry:
            tool_name = "get_expiring_certificates"
        elif asks_live_data and asks_certificate:
            tool_name = "get_crew_certificates"
        elif asks_live_data and asks_vessel:
            tool_name = "list_vessels"

        if asks_documents and tool_name:
            mode = "combined"
        elif asks_documents:
            mode = "knowledge"
        elif tool_name:
            mode = "database"
        else:
            mode = "knowledge"

        return {
            "mode": mode,
            "tool_name": tool_name,
        }

    @staticmethod
    def _tool_arguments(
        tool_name: str,
        message: str,
    ) -> dict[str, Any]:
        """Build arguments for supported Spring Boot API tools."""
        match = re.search(
            r"\b(\d{1,4})\s+days?\b",
            message.casefold(),
        )

        if tool_name == "get_expired_contracts":
            return {"days": int(match.group(1)) if match else 60}

        if tool_name == "get_expiring_certificates":
            return {"days": int(match.group(1)) if match else 100}

        return {}

    async def _retrieve_knowledge(
        self,
        question: str,
    ) -> tuple[str, list[Citation]]:
        """Generate a concise answer grounded in Knowledge Base documents."""
        if self.rag_client is None:
            raise ChatServiceError(
                "Knowledge Base answer generation is not configured.",
                503,
            )

        try:
            result = await self.rag_client.ask(question)
            response = result.get("response", {})
            answer = response.get("output", {}).get("text", "").strip()

            if not answer:
                raise BedrockRagError(
                    "Bedrock returned an empty generated answer."
                )

            citations = [
                Citation(
                    text=item.get("text", ""),
                    content=item.get("content", ""),
                    location=item.get("location", {}),
                    metadata=item.get("metadata", {}),
                    source_name=item.get("source_name", "Document"),
                )
                for item in extract_citations(response)
            ]

            logger.info(
                "Bedrock answer generated | citation_count=%s latency=%.3fs",
                len(citations),
                result.get("latency", 0.0),
            )

            return answer, citations

        except BedrockRagError:
            raise
        except Exception as exc:
            logger.exception("Knowledge Base generation failed")
            raise BedrockRagError(
                "The AI service could not generate an answer from the documents."
            ) from exc

    @staticmethod
    def _format_database_answer(
        tool_name: str,
        api_response: Any,
        days: int = 60,
    ) -> str:
        """Format structured API responses handling optional Spring Boot / MarineOn envelopes into clean text."""

        if not isinstance(api_response, (dict, list)):
            return str(api_response)

        # Handle Spring Boot envelope if present, otherwise fallback to raw response
        if isinstance(api_response, dict):
            payload = api_response.get("data", api_response)
        else:
            payload = api_response

        # Extract records safely from dtoList, records, or direct list
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("dtoList", payload.get("records", payload.get("data", [])))
            if not isinstance(records, list):
                records = [payload] if payload else []
        else:
            records = []

        if not records:
            formatted_tool_name = tool_name.replace("_", " ")
            return (
                f"A comprehensive search of the live database via the {formatted_tool_name} system "
                f"indicates that there are currently no matching records available within the specified timeframe. "
                f"Please verify your search parameters or check back later when new system updates are processed."
            )

        total = payload.get("totalRecord", len(records)) if isinstance(payload, dict) else len(records)
        
        lines = [
            f"Found {total} record(s) for {tool_name.replace('_', ' ')}:",
            "",
        ]

        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                lines.append(f"{index}. {record}")
                continue

            # Identify a primary display name
            primary_name = (
                record.get("crewName") 
                or record.get("vesselName") 
                or record.get("name") 
                or record.get("title") 
                or f"Record {index}"
            )

            # Collect remaining attributes dynamically for a clean summary
            details = []
            for k, v in record.items():
                if k in ("id", "crewId", "vesselId", "crewName", "vesselName", "name", "title"):
                    continue
                if v is not None and str(v).strip() != "":
                    formatted_key = k.replace("_", " ").title()
                    details.append(f"{formatted_key}: {v}")

            detail_str = " | ".join(details)
            if detail_str:
                lines.append(f"{index}. **{primary_name}** — {detail_str}")
            else:
                lines.append(f"{index}. **{primary_name}**")

        return "\n".join(lines)

    async def _retrieve_database(
        self,
        *,
        tool_name: str,
        message: str,
        auth_context: dict[str, Any],
        request_id: str,
    ) -> str:
        """Fetch live data through the authorized Spring Boot / MarineOn API client."""
        if self.tool_client is None:
            raise BedrockToolError(
                "Database API client is not configured"
            )

        args = self._tool_arguments(tool_name, message)
        result = await self.tool_client.execute(
            tool_name=tool_name,
            arguments=args,
            auth_context=auth_context,
            request_id=request_id,
        )

        # Support both wrapped {"data": ...} and direct unwrapped payloads from MarineOn
        api_data = result.get("data", result) if isinstance(result, dict) else result

        return self._format_database_answer(
            tool_name,
            api_data,
            days=args.get("days", 60),
        )

    async def run(
        self,
        payload,
        auth_context: dict[str, Any],
    ) -> ChatResponse:
        started = time.perf_counter()
        message = payload.message.strip()

        if not message:
            raise ChatServiceError(
                "Message cannot be empty.",
                status.HTTP_400_BAD_REQUEST,
            )

        if len(message) > self.settings.max_message_chars:
            raise ChatServiceError(
                "Message is too long",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        user_id = auth_context.get("user_id")
        if not user_id:
            raise ChatServiceError(
                "Authenticated user information is missing",
                status.HTTP_401_UNAUTHORIZED,
            )

        key = self.store.base_key(
            user_id,
            payload.conversation_id,
        )

        logger.info(
            "Chat request | request_id=%s conversation_id=%s user_id=%s",
            payload.request_id,
            payload.conversation_id,
            user_id,
        )

        try:
            async with self.store.conversation_lock(key):
                route = self._select_route(message)

                logger.info(
                    "Routing decision | request_id=%s mode=%s tool=%s",
                    payload.request_id,
                    route["mode"],
                    route["tool_name"],
                )

                citations: list[Citation] = []
                mode = route["mode"]

                if mode == "knowledge":
                    answer, citations = await self._retrieve_knowledge(
                        message,
                    )

                elif mode == "database":
                    answer = await self._retrieve_database(
                        tool_name=route["tool_name"],
                        message=message,
                        auth_context=auth_context,
                        request_id=payload.request_id,
                    )

                else:
                    kb_answer, citations = await self._retrieve_knowledge(
                        message,
                    )

                    db_text = await self._retrieve_database(
                        tool_name=route["tool_name"],
                        message=message,
                        auth_context=auth_context,
                        request_id=payload.request_id,
                    )

                    answer = (
                        f"Procedure information:\n{kb_answer}\n\n"
                        f"Live system data:\n{db_text}"
                    )

                await self.store.save_completed_turn(
                    key,
                    message,
                    answer,
                )

                latency = round(
                    time.perf_counter() - started,
                    3,
                )

                return ChatResponse(
                    requestId=payload.request_id,
                    conversationId=payload.conversation_id,
                    answer=answer,
                    citations=citations,
                    latencySeconds=latency,
                )

        except TimeoutError as exc:
            logger.warning(
                "Conversation lock timed out | request_id=%s",
                payload.request_id,
            )
            raise ChatServiceError(
                "This conversation is busy; retry shortly.",
                409,
            ) from exc

        except KnowledgeBaseError as exc:
            logger.exception(
                "Knowledge Base retrieval failed | request_id=%s",
                payload.request_id,
            )
            raise ChatServiceError(
                "The AI service could not retrieve information from the knowledge base.",
                503,
            ) from exc

        except BedrockRagError as exc:
            logger.exception(
                "Knowledge Base answer generation failed | request_id=%s",
                payload.request_id,
            )
            raise ChatServiceError(
                "The AI service could not generate an answer from the documents.",
                503,
            ) from exc

        except BedrockToolError as exc:
            logger.exception(
                "Java / MarineOn API request failed | request_id=%s",
                payload.request_id,
            )

            public_message = str(exc)
            public_status = (
                403
                if "not authorized" in public_message.casefold()
                else 503
            )

            raise ChatServiceError(
                public_message
                if public_status == 403
                else "The AI service could not retrieve live database information.",
                public_status,
            ) from exc

        except ChatServiceError:
            raise

        except Exception as exc:
            logger.exception(
                "Unexpected chat failure | request_id=%s",
                payload.request_id,
            )
            raise ChatServiceError(
                "The AI service encountered an unexpected error.",
                500,
            ) from exc