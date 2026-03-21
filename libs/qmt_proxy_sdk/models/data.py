from typing import Any

from pydantic import BaseModel

from app.models.data_models import (
    ConvertibleBondInfo,
    DataDirResponse,
    ETFInfoResponse,
    FinancialDataResponse,
    HolidayInfo,
    IndexWeightResponse,
    InstrumentInfo,
    InstrumentTypeInfo,
    IpoInfo,
    MarketDataResponse,
    PeriodListResponse,
    SectorResponse,
    TradingCalendarResponse,
)


class SubscriptionCreateResult(BaseModel):
    subscription_id: str
    status: str
    created_at: str | None = None
    symbols: list[str] | None = None
    period: str | None = None
    start_date: str | None = None
    adjust_type: str | None = None
    subscription_type: str | None = None
    message: str | None = None


class SubscriptionDeleteResult(BaseModel):
    success: bool
    message: str
    subscription_id: str


class SubscriptionInfo(BaseModel):
    subscription_id: str
    active: bool
    symbols: list[str] | None = None
    adjust_type: str | None = None
    subscription_type: str | None = None
    created_at: str | None = None
    last_heartbeat: str | None = None
    queue_size: int | None = None


class SubscriptionListResult(BaseModel):
    subscriptions: list[Any]
    total: int

__all__ = [
    "ConvertibleBondInfo",
    "DataDirResponse",
    "ETFInfoResponse",
    "FinancialDataResponse",
    "HolidayInfo",
    "IndexWeightResponse",
    "InstrumentInfo",
    "InstrumentTypeInfo",
    "IpoInfo",
    "MarketDataResponse",
    "PeriodListResponse",
    "SectorResponse",
    "SubscriptionCreateResult",
    "SubscriptionDeleteResult",
    "SubscriptionInfo",
    "SubscriptionListResult",
    "TradingCalendarResponse",
]
