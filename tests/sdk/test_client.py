import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBS_ROOT = PROJECT_ROOT / "libs"

if str(LIBS_ROOT) not in sys.path:
    sys.path.insert(0, str(LIBS_ROOT))


def _load_sdk_module(module_name: str):
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"Expected module '{module_name}' to exist under libs/"
    return importlib.import_module(module_name)


class DummyTransport:
    def __init__(self):
        self.closed = False
        self.calls = []

    async def aclose(self):
        self.closed = True

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"ok": True}


@pytest.mark.asyncio
async def test_client_closes_owned_transport():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    client = client_cls(base_url="http://localhost:8000", api_key="dev-api-key-001")
    transport = getattr(client, "_transport", None)
    assert transport is not None, "Expected client to create an internal transport"

    await client.aclose()

    underlying_client = getattr(transport, "_client", None)
    assert underlying_client is not None, "Expected transport to own an httpx.AsyncClient"
    assert underlying_client.is_closed is True


@pytest.mark.asyncio
async def test_client_does_not_close_injected_transport():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = DummyTransport()
    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    await client.aclose()

    assert transport.closed is False


@pytest.mark.asyncio
async def test_client_proxies_requests_to_transport():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = DummyTransport()
    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    result = await client.request("GET", "/health/")

    assert result == {"ok": True}
    assert transport.calls == [("GET", "/health/", {})]


@pytest.mark.asyncio
async def test_client_async_context_manager_closes_owned_transport():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    async with client_cls(base_url="http://localhost:8000", api_key="dev-api-key-001") as client:
        transport = getattr(client, "_transport", None)
        assert transport is not None, "Expected client to create an internal transport"

    underlying_client = getattr(transport, "_client", None)
    assert underlying_client is not None, "Expected transport to own an httpx.AsyncClient"
    assert underlying_client.is_closed is True
