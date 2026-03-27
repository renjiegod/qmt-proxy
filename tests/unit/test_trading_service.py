from types import SimpleNamespace

import pytest

import app.services.trading_service as trading_service_module
from app.config import Settings, XTQuantMode
from app.models.trading_models import (
    AccountInfo,
    AccountType,
    CancelOrderRequest,
    OrderRequest,
    OrderSide,
    OrderType,
)
from app.services.trading_service import TradingService
from app.utils.exceptions import TradingServiceException


def make_settings(mode: XTQuantMode, allow_real_trading: bool = False) -> Settings:
    settings = Settings()
    settings.xtquant.mode = mode
    settings.xtquant.trading.allow_real_trading = allow_real_trading
    return settings


def register_real_session(service: TradingService, session_id: str = "real-session") -> str:
    service._connected_accounts[session_id] = {
        "account_id": "acct-001",
        "account_type": "SECURITY",
        "account": object(),
        "connected_time": object(),
    }
    return session_id


def test_dev_positions_raises_instead_of_returning_mock_when_real_backend_unavailable(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = False
    session_id = register_real_session(service)

    with pytest.raises(TradingServiceException, match="xttrader|初始化|backend|连接"):
        service.get_positions(session_id)


def test_dev_asset_raises_instead_of_returning_mock_when_real_backend_unavailable(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = False
    session_id = register_real_session(service)

    with pytest.raises(TradingServiceException, match="xttrader|初始化|backend|连接"):
        service.get_asset_info(session_id)


def test_dev_positions_raise_for_unknown_session(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True

    with pytest.raises(TradingServiceException, match="账户未连接|session"):
        service.get_positions("missing-session")


def test_mock_mode_positions_still_return_simulated_data():
    service = TradingService(make_settings(XTQuantMode.MOCK))
    response = service.connect_account(
        SimpleNamespace(account_id="acct-001", password="pw", client_id=1)
    )

    positions = service.get_positions(response.session_id)

    assert response.success is True
    assert isinstance(positions, list)


def test_non_prod_submit_order_does_not_call_real_xttrader(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV, allow_real_trading=False))
    session_id = register_real_session(service)

    called = {"order_stock": 0}

    def fake_order_stock(*args, **kwargs):
        called["order_stock"] += 1
        return "should-not-happen"

    monkeypatch.setattr(
        service,
        "_xt_trader",
        SimpleNamespace(order_stock=fake_order_stock),
    )

    response = service.submit_order(
        session_id,
        OrderRequest(
            stock_code="000001.SZ",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            volume=100,
            price=10.0,
        ),
    )

    assert response.order_id.startswith("mock_order_")
    assert called["order_stock"] == 0


def test_non_prod_cancel_does_not_call_real_xttrader(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV, allow_real_trading=False))
    session_id = register_real_session(service)

    called = {"cancel_order_stock": 0}

    def fake_cancel_order_stock(*args, **kwargs):
        called["cancel_order_stock"] += 1
        return False

    monkeypatch.setattr(
        service,
        "_xt_trader",
        SimpleNamespace(cancel_order_stock=fake_cancel_order_stock),
    )

    success = service.cancel_order(session_id, CancelOrderRequest(order_id="broker-order-001"))

    assert success is True
    assert called["cancel_order_stock"] == 0


def test_dev_connect_returns_unsuccessful_response_when_real_backend_not_ready(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = False

    response = service.connect_account(
        SimpleNamespace(account_id="acct-001", password="pw", client_id=1)
    )

    assert response.success is False
    assert response.session_id is None
    assert "xttrader" in response.message or "初始化" in response.message


def test_dev_connect_stores_real_account_context(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True

    fake_account = SimpleNamespace(account_id="acct-001", account_type="SECURITY")

    monkeypatch.setattr(service, "_connect_real_account", lambda request: fake_account)
    monkeypatch.setattr(
        service,
        "_build_account_info_from_real_account",
        lambda account: AccountInfo(
            account_id="acct-001",
            account_type=AccountType.SECURITY,
            account_name="acct-001",
            status="CONNECTED",
            balance=1.0,
            available_balance=1.0,
            frozen_balance=0.0,
            market_value=0.0,
            total_asset=1.0,
        ),
    )

    response = service.connect_account(
        SimpleNamespace(account_id="acct-001", password="pw", client_id=1)
    )

    assert response.success is True
    assert response.session_id in service._connected_accounts
    assert service._connected_accounts[response.session_id]["account"] is fake_account


def test_dev_positions_map_real_qmt_objects(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    fake_position = SimpleNamespace(
        stock_code="000001.SZ",
        stock_name="平安银行",
        volume=100,
        can_use_volume=80,
        open_price=10.0,
        market_value=1050.0,
        last_price=10.5,
    )

    monkeypatch.setattr(service, "_query_real_positions", lambda session: [fake_position])

    positions = service.get_positions(session_id)

    assert len(positions) == 1
    assert positions[0].stock_code == "000001.SZ"
    assert positions[0].available_volume == 80
    assert positions[0].cost_price == 10.0
    assert positions[0].market_price == 10.5


def test_dev_positions_returns_empty_list_for_empty_real_result(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    monkeypatch.setattr(service, "_query_real_positions", lambda session: [])

    assert service.get_positions(session_id) == []


def test_dev_asset_maps_real_qmt_object(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    fake_asset = SimpleNamespace(
        total_asset=100000.0,
        market_value=25000.0,
        cash=70000.0,
        frozen_cash=5000.0,
        available_cash=65000.0,
    )

    monkeypatch.setattr(service, "_query_real_asset", lambda session: fake_asset)

    asset = service.get_asset_info(session_id)

    assert asset.total_asset == 100000.0
    assert asset.market_value == 25000.0
    assert asset.cash == 70000.0
    assert asset.available_cash == 65000.0


def test_dev_orders_map_real_qmt_results(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    fake_order = SimpleNamespace(
        order_id="broker-order-001",
        stock_code="000001.SZ",
        side="BUY",
        order_type="LIMIT",
        order_volume=100,
        price=10.0,
        order_status="SUBMITTED",
        traded_volume=20,
        traded_amount=200.0,
        traded_price=10.0,
    )

    monkeypatch.setattr(service, "_query_real_orders", lambda session: [fake_order])

    orders = service.get_orders(session_id)

    assert len(orders) == 1
    assert orders[0].order_id == "broker-order-001"
    assert orders[0].filled_volume == 20


def test_dev_orders_use_broker_truth_not_local_cache(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)
    service._orders["mock_order_1"] = SimpleNamespace(order_id="mock_order_1")

    monkeypatch.setattr(service, "_query_real_orders", lambda session: [])

    assert service.get_orders(session_id) == []


def test_dev_trades_map_real_qmt_results(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    fake_trade = SimpleNamespace(
        traded_id="trade-001",
        order_id="broker-order-001",
        stock_code="000001.SZ",
        side="BUY",
        traded_volume=100,
        traded_price=10.5,
        traded_amount=1050.0,
        traded_time="20260327103000",
        commission=1.2,
    )

    monkeypatch.setattr(service, "_query_real_trades", lambda session: [fake_trade])

    trades = service.get_trades(session_id)

    assert len(trades) == 1
    assert trades[0].trade_id == "trade-001"
    assert trades[0].amount == 1050.0


def test_dev_trades_returns_empty_list_for_empty_real_result(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    monkeypatch.setattr(service, "_query_real_trades", lambda session: [])

    assert service.get_trades(session_id) == []


def test_prod_submit_order_calls_real_xttrader_when_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.PROD, allow_real_trading=True))
    service._initialized = True
    session_id = register_real_session(service)

    called = {"order_stock": 0}

    def fake_order_stock(*args):
        called["order_stock"] += 1
        assert args[0] is service._connected_accounts[session_id]["account"]
        assert args[1] == "000001.SZ"
        assert args[3] == 100
        assert args[5] == 10.0
        return "broker-order-001"

    monkeypatch.setattr(service, "_xt_trader", SimpleNamespace(order_stock=fake_order_stock))

    response = service.submit_order(
        session_id,
        OrderRequest(
            stock_code="000001.SZ",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            volume=100,
            price=10.0,
        ),
    )

    assert response.order_id == "broker-order-001"
    assert called["order_stock"] == 1


def test_prod_cancel_calls_real_xttrader_when_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.PROD, allow_real_trading=True))
    service._initialized = True
    session_id = register_real_session(service)

    called = {"cancel_order_stock": 0}

    def fake_cancel_order_stock(account, order_id):
        called["cancel_order_stock"] += 1
        assert account is service._connected_accounts[session_id]["account"]
        assert order_id == "broker-order-001"
        return True

    monkeypatch.setattr(
        service,
        "_xt_trader",
        SimpleNamespace(cancel_order_stock=fake_cancel_order_stock),
    )

    assert service.cancel_order(session_id, CancelOrderRequest(order_id="broker-order-001")) is True
    assert called["cancel_order_stock"] == 1


def test_prod_without_allow_real_trading_still_does_not_call_real_xttrader(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.PROD, allow_real_trading=False))
    service._initialized = True
    session_id = register_real_session(service)

    called = {"order_stock": 0, "cancel_order_stock": 0}

    def fake_order_stock(*args, **kwargs):
        called["order_stock"] += 1
        return "should-not-happen"

    def fake_cancel_order_stock(*args, **kwargs):
        called["cancel_order_stock"] += 1
        return False

    monkeypatch.setattr(
        service,
        "_xt_trader",
        SimpleNamespace(
            order_stock=fake_order_stock,
            cancel_order_stock=fake_cancel_order_stock,
        ),
    )

    order_response = service.submit_order(
        session_id,
        OrderRequest(
            stock_code="000001.SZ",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            volume=100,
            price=10.0,
        ),
    )
    cancel_success = service.cancel_order(session_id, CancelOrderRequest(order_id="broker-order-001"))

    assert order_response.order_id.startswith("mock_order_")
    assert cancel_success is True
    assert called["order_stock"] == 0
    assert called["cancel_order_stock"] == 0


def test_dev_account_info_maps_real_qmt_account(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    fake_account_info = SimpleNamespace(
        account_id="acct-001",
        account_type="SECURITY",
        account_name="主账户",
        balance=100000.0,
        available_balance=90000.0,
        frozen_balance=10000.0,
        market_value=30000.0,
        total_asset=130000.0,
        status="CONNECTED",
    )

    monkeypatch.setattr(service, "_query_real_account_info", lambda session: fake_account_info)

    account = service.get_account_info(session_id)

    assert account.account_id == "acct-001"
    assert account.total_asset == 130000.0
    assert account.available_balance == 90000.0


def test_dev_account_info_raises_when_real_query_fails(monkeypatch):
    monkeypatch.setattr(trading_service_module, "XTQUANT_AVAILABLE", True)
    service = TradingService(make_settings(XTQuantMode.DEV))
    service._initialized = True
    session_id = register_real_session(service)

    def raise_query_error(session):
        raise RuntimeError("backend down")

    monkeypatch.setattr(service, "_query_real_account_info", raise_query_error)

    with pytest.raises(TradingServiceException, match="账户|QMT|backend"):
        service.get_account_info(session_id)
