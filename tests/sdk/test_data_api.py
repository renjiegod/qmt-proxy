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
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


@pytest.mark.asyncio
async def test_client_exposes_data_api_with_typed_query_models():
    client_module = _load_sdk_module("qmt_proxy_sdk.client")
    client_cls = getattr(client_module, "AsyncQmtProxyClient", None)
    assert client_cls is not None, "Expected AsyncQmtProxyClient to be exported"

    transport = RecordingTransport(
        {
            ("POST", "/api/v1/data/market"): [
                {
                    "stock_code": "000001.SZ",
                    "data": [{"close": 10.5}],
                    "fields": ["close"],
                    "period": "1d",
                    "start_date": "20240101",
                    "end_date": "20240131",
                }
            ],
            ("GET", "/api/v1/data/sectors"): [
                {
                    "sector_name": "银行",
                    "stock_list": ["000001.SZ"],
                    "sector_type": "industry",
                }
            ],
            ("POST", "/api/v1/data/sector"): {
                "sector_name": "银行",
                "stock_list": ["000001.SZ"],
                "sector_type": "industry",
            },
            ("POST", "/api/v1/data/index-weight"): {
                "index_code": "000300.SH",
                "date": "20240131",
                "weights": [{"stock_code": "000001.SZ", "weight": 0.1}],
            },
            ("GET", "/api/v1/data/trading-calendar/2024"): {
                "trading_dates": ["20240102"],
                "holidays": ["20240101"],
                "year": 2024,
            },
            ("GET", "/api/v1/data/instrument/000001.SZ"): {
                "ExchangeID": "SZ",
                "InstrumentID": "000001",
                "InstrumentName": "平安银行",
            },
            ("GET", "/api/v1/data/etf/510300.SH"): {
                "etf_code": "510300.SH",
                "etf_name": "沪深300ETF",
                "underlying_asset": "沪深300",
                "creation_unit": 1000000,
                "redemption_unit": 1000000,
            },
            ("GET", "/api/v1/data/holidays"): {"holidays": ["20240101"]},
            ("GET", "/api/v1/data/period-list"): {"periods": ["1d", "1m"]},
            ("GET", "/api/v1/data/data-dir"): {"data_dir": "C:/qmt/data"},
        }
    )
    client = client_cls(
        base_url="http://localhost:8000",
        api_key="dev-api-key-001",
        transport=transport,
    )

    market = await client.data.get_market_data(
        stock_codes=["000001.SZ"],
        start_date="20240101",
        end_date="20240131",
    )
    sectors = await client.data.get_sector_list()
    sector = await client.data.get_stock_list_in_sector("银行")
    index_weight = await client.data.get_index_weight("000300.SH", date="20240131")
    calendar = await client.data.get_trading_calendar(2024)
    instrument = await client.data.get_instrument_info("000001.SZ")
    etf = await client.data.get_etf_info("510300.SH")
    holidays = await client.data.get_holidays()
    periods = await client.data.get_period_list()
    data_dir = await client.data.get_data_dir()

    assert market[0].stock_code == "000001.SZ"
    assert sectors[0].sector_name == "银行"
    assert sector.stock_list == ["000001.SZ"]
    assert index_weight.index_code == "000300.SH"
    assert calendar.year == 2024
    assert instrument.InstrumentID == "000001"
    assert etf.etf_code == "510300.SH"
    assert holidays.holidays == ["20240101"]
    assert periods.periods == ["1d", "1m"]
    assert data_dir.data_dir == "C:/qmt/data"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs", "expected_method", "expected_path", "expected_kwargs", "response"),
    [
        (
            "get_financial_data",
            {"stock_codes": ["000001.SZ"], "table_list": ["balance"], "start_date": "20240101", "end_date": "20240131"},
            "POST",
            "/api/v1/data/financial",
            {"json": {"stock_codes": ["000001.SZ"], "table_list": ["balance"], "start_date": "20240101", "end_date": "20240131"}},
            [{"stock_code": "000001.SZ", "table_name": "balance", "data": [], "columns": []}],
        ),
        (
            "get_instrument_type",
            {"stock_code": "000001.SZ"},
            "GET",
            "/api/v1/data/instrument-type/000001.SZ",
            {},
            {
                "stock_code": "000001.SZ",
                "index": False,
                "stock": True,
                "fund": False,
                "etf": False,
                "bond": False,
                "option": False,
                "futures": False,
            },
        ),
        (
            "get_convertible_bonds",
            {},
            "GET",
            "/api/v1/data/convertible-bonds",
            {},
            [{"bond_code": "110000"}],
        ),
        (
            "get_ipo_info",
            {},
            "GET",
            "/api/v1/data/ipo-info",
            {},
            [{"security_code": "301000"}],
        ),
        (
            "get_local_data",
            {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/local-data",
            {"json": {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131", "period": "1d", "fields": None, "adjust_type": "none"}},
            {"items": 1},
        ),
        (
            "get_full_tick",
            {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/full-tick",
            {"json": {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"}},
            {"ticks": []},
        ),
        (
            "get_divid_factors",
            {"stock_code": "000001.SZ"},
            "POST",
            "/api/v1/data/divid-factors",
            {"json": {"stock_code": "000001.SZ"}},
            [{"time": "20240101"}],
        ),
        (
            "get_full_kline",
            {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/full-kline",
            {"json": {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131", "period": "1d", "fields": None, "adjust_type": "none"}},
            {"kline": []},
        ),
        (
            "download_history_data",
            {"stock_code": "000001.SZ", "period": "1d", "start_time": "20240101", "end_time": "20240131", "incrementally": True},
            "POST",
            "/api/v1/data/download/history-data",
            {"json": {"stock_code": "000001.SZ", "period": "1d", "start_time": "20240101", "end_time": "20240131", "incrementally": True}},
            {"task_id": "hist-1"},
        ),
        (
            "download_history_data_batch",
            {"stock_list": ["000001.SZ"], "period": "1d", "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/download/history-data-batch",
            {"json": {"stock_list": ["000001.SZ"], "period": "1d", "start_time": "20240101", "end_time": "20240131"}},
            {"task_id": "hist-batch-1"},
        ),
        (
            "download_financial_data",
            {"stock_list": ["000001.SZ"], "table_list": ["balance"], "start_date": "20240101", "end_date": "20240131"},
            "POST",
            "/api/v1/data/download/financial-data",
            {"json": {"stock_list": ["000001.SZ"], "table_list": ["balance"], "start_date": "20240101", "end_date": "20240131"}},
            {"task_id": "fin-1"},
        ),
        (
            "download_financial_data_batch",
            {"stock_list": ["000001.SZ"], "table_list": ["balance"], "start_date": "20240101", "end_date": "20240131", "callback_func": "cb"},
            "POST",
            "/api/v1/data/download/financial-data-batch",
            {"json": {"stock_list": ["000001.SZ"], "table_list": ["balance"], "start_date": "20240101", "end_date": "20240131", "callback_func": "cb"}},
            {"task_id": "fin-batch-1"},
        ),
        ("download_sector_data", {}, "POST", "/api/v1/data/download/sector-data", {}, {"task_id": "sector-1"}),
        (
            "download_index_weight",
            {"index_code": "000300.SH"},
            "POST",
            "/api/v1/data/download/index-weight",
            {"json": {"index_code": "000300.SH"}},
            {"task_id": "index-1"},
        ),
        ("download_cb_data", {}, "POST", "/api/v1/data/download/cb-data", {}, {"task_id": "cb-1"}),
        ("download_etf_info", {}, "POST", "/api/v1/data/download/etf-info", {}, {"task_id": "etf-1"}),
        ("download_holiday_data", {}, "POST", "/api/v1/data/download/holiday-data", {}, {"task_id": "holiday-1"}),
        (
            "download_history_contracts",
            {"market": "SH"},
            "POST",
            "/api/v1/data/download/history-contracts",
            {"json": {"market": "SH"}},
            {"task_id": "contract-1"},
        ),
        (
            "create_sector_folder",
            {"parent_node": "我的", "folder_name": "行业"},
            "POST",
            "/api/v1/data/sector/create-folder",
            {"params": {"parent_node": "我的", "folder_name": "行业"}},
            {"created_name": "行业"},
        ),
        (
            "create_sector",
            {"sector_name": "自选板块", "parent_node": "我的", "overwrite": False},
            "POST",
            "/api/v1/data/sector/create",
            {"json": {"parent_node": "我的", "sector_name": "自选板块", "overwrite": False}},
            {"created_name": "自选板块"},
        ),
        (
            "add_sector_stocks",
            {"sector_name": "自选板块", "stock_list": ["000001.SZ"]},
            "POST",
            "/api/v1/data/sector/add-stocks",
            {"json": {"sector_name": "自选板块", "stock_list": ["000001.SZ"]}},
            None,
        ),
        (
            "remove_sector_stocks",
            {"sector_name": "自选板块", "stock_list": ["000001.SZ"]},
            "POST",
            "/api/v1/data/sector/remove-stocks",
            {"json": {"sector_name": "自选板块", "stock_list": ["000001.SZ"]}},
            None,
        ),
        (
            "remove_sector",
            {"sector_name": "自选板块"},
            "POST",
            "/api/v1/data/sector/remove",
            {"params": {"sector_name": "自选板块"}},
            None,
        ),
        (
            "reset_sector",
            {"sector_name": "自选板块", "stock_list": ["000001.SZ"]},
            "POST",
            "/api/v1/data/sector/reset",
            {"json": {"sector_name": "自选板块", "stock_list": ["000001.SZ"]}},
            None,
        ),
        (
            "get_l2_quote",
            {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/l2/quote",
            {"json": {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"}},
            {"quotes": []},
        ),
        (
            "get_l2_order",
            {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/l2/order",
            {"json": {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"}},
            {"orders": []},
        ),
        (
            "get_l2_transaction",
            {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"},
            "POST",
            "/api/v1/data/l2/transaction",
            {"json": {"stock_codes": ["000001.SZ"], "start_time": "20240101", "end_time": "20240131"}},
            {"transactions": []},
        ),
        (
            "create_subscription",
            {"symbols": ["000001.SZ"], "period": "tick", "start_date": "20240101", "adjust_type": "none", "subscription_type": "quote"},
            "POST",
            "/api/v1/data/subscription",
            {"json": {"symbols": ["000001.SZ"], "period": "tick", "start_date": "20240101", "adjust_type": "none", "subscription_type": "quote"}},
            {"subscription_id": "sub-1", "status": "active"},
        ),
        (
            "delete_subscription",
            {"subscription_id": "sub-1"},
            "DELETE",
            "/api/v1/data/subscription/sub-1",
            {},
            {"success": True, "message": "订阅已取消", "subscription_id": "sub-1"},
        ),
        (
            "get_subscription",
            {"subscription_id": "sub-1"},
            "GET",
            "/api/v1/data/subscription/sub-1",
            {},
            {"subscription_id": "sub-1", "active": True},
        ),
        (
            "list_subscriptions",
            {},
            "GET",
            "/api/v1/data/subscriptions",
            {},
            {"subscriptions": [], "total": 0},
        ),
    ],
)
async def test_data_api_routes_extended_rest_surface(
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

    method = getattr(client.data, method_name)
    result = await method(**kwargs)

    assert _normalize(result) == response
    assert transport.calls == [(expected_method, expected_path, expected_kwargs)]
