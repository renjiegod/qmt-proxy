from pydantic import BaseModel

from app.models.trading_models import (
    AccountInfo,
    AssetInfo,
    ConnectResponse,
    OrderResponse,
    PositionInfo,
    RiskInfo,
    StrategyInfo,
    TradeInfo,
)


class OperationResult(BaseModel):
    success: bool


class ConnectionStatus(BaseModel):
    connected: bool


__all__ = [
    "AccountInfo",
    "AssetInfo",
    "ConnectResponse",
    "ConnectionStatus",
    "OperationResult",
    "OrderResponse",
    "PositionInfo",
    "RiskInfo",
    "StrategyInfo",
    "TradeInfo",
]
