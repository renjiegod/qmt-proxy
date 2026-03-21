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


class RecordingTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.responses[(method, path)]

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_client_exposes_system_api_with_typed_health_responses():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = RecordingTransport(
        {
            ("GET", "/health/"): {
                "status": "healthy",
                "app_name": "xtquant-proxy",
                "app_version": "1.0.0",
                "xtquant_mode": "dev",
                "timestamp": "2026-03-21T12:00:00",
            },
            ("GET", "/health/ready"): {"status": "ready"},
            ("GET", "/health/live"): {"status": "alive"},
        }
    )
    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    health = await client.system.check_health()
    ready = await client.system.check_ready()
    live = await client.system.check_live()

    assert health.status == "healthy"
    assert health.app_name == "xtquant-proxy"
    assert ready.status == "ready"
    assert live.status == "alive"
    assert transport.calls == [
        ("GET", "/health/", {}),
        ("GET", "/health/ready", {}),
        ("GET", "/health/live", {}),
    ]


@pytest.mark.asyncio
async def test_system_api_returns_root_and_app_info_models():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = RecordingTransport(
        {
            ("GET", "/"): {
                "app_name": "xtquant-proxy",
                "app_version": "1.0.0",
                "xtquant_mode": "dev",
                "description": "基于xtquant的量化交易代理服务",
                "docs_url": "/docs",
                "redoc_url": "/redoc",
            },
            ("GET", "/info"): {
                "name": "xtquant-proxy",
                "version": "1.0.0",
                "debug": False,
                "host": "0.0.0.0",
                "port": 8000,
                "log_level": "DEBUG",
                "xtquant_mode": "dev",
                "allow_real_trading": False,
            },
        }
    )
    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    root_info = await client.system.get_root()
    app_info = await client.system.get_info()

    assert root_info.docs_url == "/docs"
    assert root_info.redoc_url == "/redoc"
    assert app_info.name == "xtquant-proxy"
    assert app_info.allow_real_trading is False
