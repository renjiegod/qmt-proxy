import importlib
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBS_ROOT = PROJECT_ROOT / "libs"

if str(LIBS_ROOT) not in sys.path:
    sys.path.insert(0, str(LIBS_ROOT))


def _load_sdk_module(module_name: str):
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"Expected module '{module_name}' to exist under libs/"
    return importlib.import_module(module_name)


@pytest.mark.asyncio
async def test_transport_adds_bearer_auth_and_unwraps_enveloped_data():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            status_code=200,
            json={
                "success": True,
                "message": "ok",
                "code": 200,
                "timestamp": "2026-03-21T12:00:00",
                "data": {"status": "healthy"},
            },
        )

    http_module = _load_sdk_module("qmt_proxy_sdk.http")
    transport_cls = getattr(http_module, "AsyncHttpTransport", None)
    assert transport_cls is not None, "Expected AsyncHttpTransport to be exported"

    transport = transport_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=httpx.MockTransport(handler),
    )

    payload = await transport.request("GET", "/health/")

    assert captured == {
        "method": "GET",
        "path": "/health/",
        "auth": "Bearer dev-api-key-001",
    }
    assert payload == {"status": "healthy"}

    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_keeps_raw_json_for_non_enveloped_payloads():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"session_id": "session-001", "message": "connected"},
        )

    http_module = _load_sdk_module("qmt_proxy_sdk.http")
    transport_cls = getattr(http_module, "AsyncHttpTransport", None)
    assert transport_cls is not None, "Expected AsyncHttpTransport to be exported"

    transport = transport_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=httpx.MockTransport(handler),
    )

    payload = await transport.request("POST", "/api/v1/trading/connect", json={"account_id": "demo"})

    assert payload == {"session_id": "session-001", "message": "connected"}

    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_maps_http_errors_to_sdk_exceptions():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=401,
            json={
                "success": False,
                "message": "API密钥缺失",
                "code": 401,
                "timestamp": "2026-03-21T12:00:00",
            },
        )

    http_module = _load_sdk_module("qmt_proxy_sdk.http")
    exceptions_module = _load_sdk_module("qmt_proxy_sdk.exceptions")
    transport_cls = getattr(http_module, "AsyncHttpTransport", None)
    auth_error_cls = getattr(exceptions_module, "AuthenticationError", None)

    assert transport_cls is not None, "Expected AsyncHttpTransport to be exported"
    assert auth_error_cls is not None, "Expected AuthenticationError to be exported"

    transport = transport_cls(
        base_url="http://localhost:8000",
        api_key="bad-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(auth_error_cls) as exc_info:
        await transport.request("GET", "/api/v1/data/sectors")

    assert "API密钥缺失" in str(exc_info.value)
    assert exc_info.value.code == 401

    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_normalizes_error_code_to_int():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=422,
            json={
                "success": False,
                "message": "bad payload",
                "code": "422",
                "timestamp": "2026-03-21T12:00:00",
            },
        )

    http_module = _load_sdk_module("qmt_proxy_sdk.http")
    exceptions_module = _load_sdk_module("qmt_proxy_sdk.exceptions")
    transport_cls = getattr(http_module, "AsyncHttpTransport", None)
    validation_error_cls = getattr(exceptions_module, "RequestValidationError", None)

    assert transport_cls is not None, "Expected AsyncHttpTransport to be exported"
    assert validation_error_cls is not None, "Expected RequestValidationError to be exported"

    transport = transport_cls(
        base_url="http://localhost:8000",
        api_key="bad-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(validation_error_cls) as exc_info:
        await transport.request("POST", "/api/v1/data/market", json={})

    assert exc_info.value.code == 422

    await transport.aclose()
