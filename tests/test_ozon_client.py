import asyncio

import httpx
import pytest

from sut_control_center.ozon.client import OzonClient
from sut_control_center.ozon.errors import OzonAuthError, OzonHTTPError, OzonNetworkError, OzonResponseError


def client(handler, *, retries=0):
    return OzonClient("client-id", "api-key", transport=httpx.MockTransport(handler), max_retries=retries)


def test_successful_response_and_auth_headers():
    def handler(request):
        assert request.headers["Client-Id"] == "client-id"
        assert request.headers["Api-Key"] == "api-key"
        return httpx.Response(200, json={"result": "ok"})
    response = asyncio.run(client(handler).post("/v1/example", json={"id": 1}))
    assert response.status_code == 200 and response.data == {"result": "ok"}


def test_4xx_response():
    with pytest.raises(OzonAuthError, match="HTTP 403"):
        asyncio.run(client(lambda _: httpx.Response(403)).get("/v1/example"))


def test_5xx_response_retries_are_limited():
    attempts = 0
    def handler(_request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)
    with pytest.raises(OzonHTTPError, match="HTTP 503"):
        asyncio.run(client(handler, retries=2).get("/v1/example"))
    assert attempts == 3


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)
    with pytest.raises(OzonNetworkError, match="timed out"):
        asyncio.run(client(handler).get("/v1/example"))


def test_invalid_json():
    with pytest.raises(OzonResponseError, match="invalid JSON"):
        asyncio.run(client(lambda _: httpx.Response(200, content=b"not-json")).get("/v1/example"))
