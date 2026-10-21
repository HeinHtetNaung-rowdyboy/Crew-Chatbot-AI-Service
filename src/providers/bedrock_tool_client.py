
import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from src.tools.registry import TOOL_NAMES

logger = logging.getLogger(__name__)


class BedrockToolError(Exception):
    """Raised when a live Java API operation fails."""


class BedrockToolClient:
    """Calls allowlisted Spring Boot APIs using the user's JWT.

    Automatically fetches all pages for paginated dashboard endpoints.
    Database results are not rewritten by an LLM.
    """

    DEFAULT_PAGE_SIZE = 10
    MAX_PAGES = 100

    def __init__(
        self,
        client=None,
        model_id: str | None = None,
        java_api_base_url: str = "",
        timeout_seconds: float = 30.0,
    ):
        self.client = client
        self.model_id = model_id
        self.java_api_base_url = java_api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

        parsed = urlparse(self.java_api_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("JAVA_API_BASE_URL is invalid")

    @staticmethod
    def _validate_days(arguments: dict[str, Any]) -> int:
        days = arguments.get("days")

        if (
            isinstance(days, bool)
            or not isinstance(days, int)
            or not 1 <= days <= 3650
        ):
            raise BedrockToolError(
                "days must be an integer between 1 and 3650"
            )

        return days

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        tool_name: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Make one authorized Java API request and parse its JSON response."""
        try:
            response = await client.get(
                url,
                params=params,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "Java API timeout | tool=%s request_id=%s",
                tool_name,
                request_id,
            )
            raise BedrockToolError(
                "The business API timed out"
            ) from exc
        except httpx.HTTPError as exc:
            logger.exception(
                "Java API connection failed | tool=%s request_id=%s",
                tool_name,
                request_id,
            )
            raise BedrockToolError(
                "The business API is temporarily unavailable"
            ) from exc

        logger.info(
            "Java API page response | tool=%s status=%s "
            "request_id=%s params=%s",
            tool_name,
            response.status_code,
            request_id,
            params,
        )

        if response.status_code in (401, 403):
            raise BedrockToolError(
                "The user is not authorized to access this data"
            )

        if response.status_code >= 400:
            logger.error(
                "Java API returned HTTP %s for %s",
                response.status_code,
                tool_name,
            )
            raise BedrockToolError(
                "The business API returned an error"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise BedrockToolError(
                "The business API returned invalid JSON"
            ) from exc

        if not isinstance(data, dict):
            raise BedrockToolError(
                "The business API returned an unexpected JSON structure"
            )

        # Some APIs use HTTP 200 for application-level failures.
        if data.get("status") is False:
            logger.error(
                "Java API reported failure | tool=%s request_id=%s",
                tool_name,
                request_id,
            )
            raise BedrockToolError(
                "The business API reported that the request failed"
            )

        return data

    @staticmethod
    def _pagination_payload(
        response_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Get the object containing totalPage, currentPage and dtoList."""
        payload = response_data.get("data", response_data)

        if not isinstance(payload, dict):
            raise BedrockToolError(
                "The paginated API returned an unexpected data structure"
            )

        return payload

    async def _get_all_pages(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        base_params: dict[str, Any],
        headers: dict[str, str],
        tool_name: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Fetch all pages and combine their dtoList records."""
        first_response = await self._get_json(
            client,
            url=url,
            params={
                **base_params,
                "page": 0,
                "size": self.DEFAULT_PAGE_SIZE,
            },
            headers=headers,
            tool_name=tool_name,
            request_id=request_id,
        )

        first_payload = self._pagination_payload(first_response)
        first_records = first_payload.get("dtoList", [])

        if not isinstance(first_records, list):
            raise BedrockToolError(
                "The paginated API returned an invalid dtoList"
            )

        try:
            total_pages = int(first_payload.get("totalPage", 1))
            total_records = int(
                first_payload.get("totalRecord", len(first_records))
            )
            page_size = int(
                first_payload.get("currentSize", self.DEFAULT_PAGE_SIZE)
            )
        except (TypeError, ValueError) as exc:
            raise BedrockToolError(
                "The paginated API returned invalid pagination metadata"
            ) from exc

        if total_pages < 0 or total_records < 0 or page_size < 1:
            raise BedrockToolError(
                "The paginated API returned invalid pagination metadata"
            )

        if total_pages > self.MAX_PAGES:
            raise BedrockToolError(
                f"The API reported more than {self.MAX_PAGES} pages; "
                "refusing to fetch an excessive number of records"
            )

        all_records = list(first_records)

        logger.info(
            "Pagination started | tool=%s total_pages=%s "
            "total_records=%s first_page_records=%s request_id=%s",
            tool_name,
            total_pages,
            total_records,
            len(first_records),
            request_id,
        )

        for page_number in range(1, total_pages):
            page_response = await self._get_json(
                client,
                url=url,
                params={
                    **base_params,
                    "page": page_number,
                    "size": page_size,
                },
                headers=headers,
                tool_name=tool_name,
                request_id=request_id,
            )

            page_payload = self._pagination_payload(page_response)
            page_records = page_payload.get("dtoList", [])

            if not isinstance(page_records, list):
                raise BedrockToolError(
                    f"The API returned an invalid dtoList on page {page_number}"
                )

            all_records.extend(page_records)

            logger.info(
                "Pagination page fetched | tool=%s page=%s "
                "records=%s request_id=%s",
                tool_name,
                page_number,
                len(page_records),
                request_id,
            )

        # Update the existing response structure without removing the
        # original API envelope or unrelated pagination fields.
        merged_response = dict(first_response)
        merged_payload = dict(first_payload)
        merged_payload["dtoList"] = all_records
        merged_payload["totalRecord"] = total_records
        merged_payload["currentSize"] = len(all_records)
        merged_payload["currentPage"] = 0
        merged_payload["totalPage"] = 1

        if "data" in first_response:
            merged_response["data"] = merged_payload
        else:
            merged_response = merged_payload

        logger.info(
            "Pagination completed | tool=%s returned_records=%s "
            "reported_total=%s request_id=%s",
            tool_name,
            len(all_records),
            total_records,
            request_id,
        )

        if len(all_records) < total_records:
            logger.warning(
                "API returned fewer records than reported | tool=%s "
                "returned=%s reported_total=%s request_id=%s",
                tool_name,
                len(all_records),
                total_records,
                request_id,
            )

        return merged_response

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None,
        auth_context: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        if tool_name not in TOOL_NAMES:
            raise BedrockToolError("Unsupported business tool")

        user_jwt = auth_context.get("access_token")
        if not user_jwt:
            raise BedrockToolError(
                "Validated user access token is missing"
            )

        arguments = arguments or {}

        if tool_name == "get_expired_contracts":
            path = "/api/dashboard/expired-contracts"
            base_params = {
                "days": self._validate_days(arguments),
            }
            paginate = True

        elif tool_name == "get_expiring_certificates":
            path = "/api/dashboard/expiring-certificates"
            base_params = {
                "days": self._validate_days(arguments),
            }
            paginate = True

        elif tool_name == "list_vessels":
            path = "/api/vessels"
            base_params = {"size": 1000}
            paginate = False

        else:
            raise BedrockToolError("Unsupported business tool")

        headers = {
            "Authorization": f"Bearer {user_jwt}",
            "Accept": "application/json",
            "X-Request-ID": request_id,
        }

        url = f"{self.java_api_base_url}{path}"
        started = time.perf_counter()

        logger.info(
            "Calling Java API | tool=%s path=%s request_id=%s",
            tool_name,
            path,
            request_id,
        )

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
            ) as client:
                if paginate:
                    data = await self._get_all_pages(
                        client,
                        url=url,
                        base_params=base_params,
                        headers=headers,
                        tool_name=tool_name,
                        request_id=request_id,
                    )
                else:
                    data = await self._get_json(
                        client,
                        url=url,
                        params=base_params,
                        headers=headers,
                        tool_name=tool_name,
                        request_id=request_id,
                    )

        except BedrockToolError:
            raise
        except Exception as exc:
            logger.exception(
                "Unexpected Java API client error | tool=%s request_id=%s",
                tool_name,
                request_id,
            )
            raise BedrockToolError(
                "The business API request failed"
            ) from exc

        logger.info(
            "Java API completed | tool=%s elapsed=%.3fs request_id=%s",
            tool_name,
            time.perf_counter() - started,
            request_id,
        )

        return {
            "tool": tool_name,
            "status_code": 200,
            "data": data,
        }
