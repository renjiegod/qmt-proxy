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


def _normalize(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


@pytest.mark.asyncio
async def test_client_exposes_trading_api_with_typed_models():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = RecordingTransport(
        {
            ("POST", "/api/v1/trading/connect"): {
                "success": True,
                "message": "connected",
                "session_id": "session-001",
                "account_info": {
                    "account_id": "acct-001",
                    "account_type": "SECURITY",
                    "account_name": "demo",
                    "status": "connected",
                    "balance": 1000.0,
                    "available_balance": 900.0,
                    "frozen_balance": 100.0,
                    "market_value": 0.0,
                    "total_asset": 1000.0,
                },
            },
            ("GET", "/api/v1/trading/account/session-001"): {
                "account_id": "acct-001",
                "account_type": "SECURITY",
                "account_name": "demo",
                "status": "connected",
                "balance": 1000.0,
                "available_balance": 900.0,
                "frozen_balance": 100.0,
                "market_value": 0.0,
                "total_asset": 1000.0,
            },
            ("GET", "/api/v1/trading/positions/session-001"): [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "volume": 100,
                    "available_volume": 100,
                    "frozen_volume": 0,
                    "cost_price": 10.0,
                    "market_price": 10.5,
                    "market_value": 1050.0,
                    "profit_loss": 50.0,
                    "profit_loss_ratio": 0.05,
                }
            ],
            ("GET", "/api/v1/trading/asset/session-001"): {
                "total_asset": 1000.0,
                "market_value": 0.0,
                "cash": 1000.0,
                "frozen_cash": 0.0,
                "available_cash": 1000.0,
                "profit_loss": 0.0,
                "profit_loss_ratio": 0.0,
            },
            ("GET", "/api/v1/trading/risk/session-001"): {
                "position_ratio": 0.0,
                "cash_ratio": 1.0,
                "max_drawdown": 0.0,
                "var_95": 0.0,
                "var_99": 0.0,
            },
            ("GET", "/api/v1/trading/strategies/session-001"): [
                {
                    "strategy_name": "grid",
                    "strategy_type": "demo",
                    "status": "running",
                    "created_time": "2026-03-21T12:00:00",
                    "last_update_time": "2026-03-21T12:05:00",
                    "parameters": {"window": 10},
                }
            ],
            ("GET", "/api/v1/trading/orders/session-001"): [
                {
                    "order_id": "order-001",
                    "stock_code": "000001.SZ",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "volume": 100,
                    "price": 10.5,
                    "status": "SUBMITTED",
                    "submitted_time": "2026-03-21T12:00:00",
                    "filled_volume": 0,
                    "filled_amount": 0.0,
                    "average_price": None,
                }
            ],
            ("GET", "/api/v1/trading/trades/session-001"): [
                {
                    "trade_id": "trade-001",
                    "order_id": "order-001",
                    "stock_code": "000001.SZ",
                    "side": "BUY",
                    "volume": 100,
                    "price": 10.5,
                    "amount": 1050.0,
                    "trade_time": "2026-03-21T12:01:00",
                    "commission": 1.0,
                }
            ],
        }
    )

    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    connect = await client.trading.connect(account_id="acct-001", password="secret")
    account = await client.trading.get_account_info("session-001")
    positions = await client.trading.get_positions("session-001")
    asset = await client.trading.get_asset("session-001")
    risk = await client.trading.get_risk("session-001")
    strategies = await client.trading.get_strategies("session-001")
    orders = await client.trading.get_orders("session-001")
    trades = await client.trading.get_trades("session-001")

    assert connect.session_id == "session-001"
    assert account.account_id == "acct-001"
    assert positions[0].stock_code == "000001.SZ"
    assert asset.cash == 1000.0
    assert risk.cash_ratio == 1.0
    assert strategies[0].strategy_name == "grid"
    assert orders[0].order_id == "order-001"
    assert trades[0].trade_id == "trade-001"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs", "expected_method", "expected_path", "expected_kwargs", "response"),
    [
        (
            "connect",
            {"account_id": "acct-001", "password": "secret"},
            "POST",
            "/api/v1/trading/connect",
            {"json": {"account_id": "acct-001", "password": "secret"}},
            {
                "success": True,
                "message": "connected",
                "session_id": "session-001",
            },
        ),
        (
            "disconnect",
            {"session_id": "session-001"},
            "POST",
            "/api/v1/trading/disconnect/session-001",
            {},
            {"success": True},
        ),
        (
            "submit_order",
            {
                "session_id": "session-001",
                "stock_code": "000001.SZ",
                "side": "BUY",
                "volume": 100,
                "price": 10.5,
                "order_type": "LIMIT",
                "strategy_name": "grid",
            },
            "POST",
            "/api/v1/trading/order/session-001",
            {"json": {"stock_code": "000001.SZ", "side": "BUY", "order_type": "LIMIT", "volume": 100, "price": 10.5, "strategy_name": "grid"}},
            {
                "order_id": "order-001",
                "stock_code": "000001.SZ",
                "side": "BUY",
                "order_type": "LIMIT",
                "volume": 100,
                "price": 10.5,
                "status": "SUBMITTED",
                "submitted_time": "2026-03-21T12:00:00",
                "filled_volume": 0,
                "filled_amount": 0.0,
            },
        ),
        (
            "cancel_order",
            {"session_id": "session-001", "order_id": "order-001"},
            "POST",
            "/api/v1/trading/cancel/session-001",
            {"json": {"order_id": "order-001"}},
            {"success": True},
        ),
        (
            "get_connection_status",
            {"session_id": "session-001"},
            "GET",
            "/api/v1/trading/status/session-001",
            {},
            {"connected": True},
        ),
    ],
)
async def test_trading_api_routes_and_payloads(
    method_name,
    kwargs,
    expected_method,
    expected_path,
    expected_kwargs,
    response,
):
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = RecordingTransport({(expected_method, expected_path): response})
    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    method = getattr(client.trading, method_name)
    result = await method(**kwargs)

    assert _normalize(result) == response
    assert transport.calls == [(expected_method, expected_path, expected_kwargs)]
