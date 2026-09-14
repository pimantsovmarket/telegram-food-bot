from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .errors import OzonAuthError, OzonHTTPError, OzonNetworkError, OzonResponseError
from .models import OzonResponse


log = logging.getLogger(__name__)


class OzonClient:
    def __init__(self, client_id: str, api_key: str, *, base_url: str = "https://api-seller.ozon.ru", timeout_seconds: float = 15.0, max_retries: int = 2, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not client_id or not api_key:
            raise ValueError("Ozon credentials are not configured")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        self._headers = {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.transport = transport

    async def request(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> OzonResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(headers=self._headers, timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = await client.request(method.upper(), url, json=json, params=params)
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise OzonNetworkError("Ozon API request timed out") from exc
            except httpx.RequestError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise OzonNetworkError("Ozon API connection failed") from exc
            if response.status_code in (401, 403):
                raise OzonAuthError(f"Ozon API authorization failed (HTTP {response.status_code})")
            if response.status_code >= 500:
                if attempt + 1 < attempts:
                    log.warning("Ozon API server error HTTP %s; retrying", response.status_code)
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise OzonHTTPError(f"Ozon API returned HTTP {response.status_code}")
            if response.is_error:
                raise OzonHTTPError(f"Ozon API returned HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise OzonResponseError("Ozon API returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise OzonResponseError("Ozon API returned an unexpected JSON structure")
            return OzonResponse(response.status_code, payload)
        raise AssertionError("unreachable")

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> OzonResponse:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None) -> OzonResponse:
        return await self.request("POST", path, json=json)

    async def probe(self) -> bool:
        """Check network reachability without making a state-changing API call."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                await client.get(self.base_url)
            return True
        except httpx.RequestError:
            return False
