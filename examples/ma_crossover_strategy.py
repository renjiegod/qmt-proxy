"""
双均线交叉量化交易策略示例
========================

本示例展示如何使用 qmt-proxy SDK 完成一个完整的量化交易流程：

1. 连接服务 & 健康检查
2. 获取沪深 300 成分股，通过历史行情数据进行选股
3. 建立交易会话
4. 通过 WebSocket 订阅目标股实时行情
5. 基于双均线（MA5/MA20）交叉策略生成买卖信号
6. 自动执行买入 / 卖出 / 空仓操作

运行方式::

    # 确保 qmt-proxy 服务已启动
    python examples/ma_crossover_strategy.py

环境变量（可选）::

    QMT_PROXY_URL   服务地址，默认 http://localhost:8000
    QMT_API_KEY     API 密钥，默认 dev-api-key-001
    QMT_ACCOUNT_ID  交易账户，默认 test_account
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from qmt_proxy_sdk import AsyncQmtProxyClient, QmtProxyError

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("策略")

# ---------------------------------------------------------------------------
# 策略参数
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("QMT_PROXY_URL", "http://localhost:8000")
API_KEY = os.getenv("QMT_API_KEY", "dev-api-key-001")
ACCOUNT_ID = os.getenv("QMT_ACCOUNT_ID", "test_account")

SHORT_MA_PERIOD = 5
LONG_MA_PERIOD = 20
SCREENING_DAYS = 60
ORDER_VOLUME = 100  # 每笔下单数量（股）
MAX_POSITIONS = 3   # 最大同时持仓数

CANDIDATE_STOCKS = [
    "600519.SH",  # 贵州茅台
    "000858.SZ",  # 五粮液
    "601318.SH",  # 中国平安
    "000333.SZ",  # 美的集团
    "600036.SH",  # 招商银行
    "000001.SZ",  # 平安银行
    "601166.SH",  # 兴业银行
    "600276.SH",  # 恒瑞医药
    "000651.SZ",  # 格力电器
    "002415.SZ",  # 海康威视
]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class StockContext:
    """单只股票的运行时上下文，保存滑动窗口价格与状态。"""

    code: str
    prices: deque = field(default_factory=lambda: deque(maxlen=LONG_MA_PERIOD))
    prev_short_ma: float | None = None
    prev_long_ma: float | None = None
    held: bool = False


def calc_ma(prices: deque, period: int) -> float | None:
    if len(prices) < period:
        return None
    return sum(list(prices)[-period:]) / period


# ---------------------------------------------------------------------------
# 阶段 1：健康检查
# ---------------------------------------------------------------------------


async def check_service(client: AsyncQmtProxyClient) -> None:
    log.info("=" * 60)
    log.info("阶段 1：服务健康检查")
    log.info("=" * 60)

    health = await client.system.check_health()
    log.info(
        "服务状态: %s | 版本: %s | 模式: %s | 时间: %s",
        health.status,
        health.app_version,
        health.xtquant_mode,
        health.timestamp,
    )

    info = await client.system.get_info()
    log.info(
        "服务详情: %s:%d | 调试=%s | 允许实盘=%s",
        info.host,
        info.port,
        info.debug,
        info.allow_real_trading,
    )


# ---------------------------------------------------------------------------
# 阶段 2：选股
# ---------------------------------------------------------------------------


async def screen_stocks(client: AsyncQmtProxyClient) -> list[str]:
    log.info("")
    log.info("=" * 60)
    log.info("阶段 2：基于历史行情选股")
    log.info("=" * 60)

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=SCREENING_DAYS)).strftime("%Y%m%d")

    log.info(
        "候选池: %d 只 | 数据区间: %s ~ %s | 周期: 1d",
        len(CANDIDATE_STOCKS),
        start_date,
        end_date,
    )

    market_results = await client.data.get_market_data(
        stock_codes=CANDIDATE_STOCKS,
        start_date=start_date,
        end_date=end_date,
        period="1d",
        fields=["close", "volume"],
    )

    selected: list[str] = []

    for item in market_results:
        code = item.stock_code
        rows = item.data
        if len(rows) < LONG_MA_PERIOD:
            log.info("  [跳过] %s — 数据不足 (%d 条，需 %d)", code, len(rows), LONG_MA_PERIOD)
            continue

        closes = [float(r["close"]) for r in rows if r.get("close") is not None]
        volumes = [float(r["volume"]) for r in rows if r.get("volume") is not None]

        if len(closes) < LONG_MA_PERIOD:
            log.info("  [跳过] %s — 有效收盘价不足", code)
            continue

        ma_short = sum(closes[-SHORT_MA_PERIOD:]) / SHORT_MA_PERIOD
        ma_long = sum(closes[-LONG_MA_PERIOD:]) / LONG_MA_PERIOD
        avg_volume = sum(volumes[-LONG_MA_PERIOD:]) / LONG_MA_PERIOD if volumes else 0
        latest_close = closes[-1]

        trend = "多头" if ma_short > ma_long else "空头"
        log.info(
            "  %s | 最新价: %.2f | MA%d: %.2f | MA%d: %.2f | "
            "均量: %.0f | 趋势: %s",
            code,
            latest_close,
            SHORT_MA_PERIOD,
            ma_short,
            LONG_MA_PERIOD,
            ma_long,
            avg_volume,
            trend,
        )

        # 选股条件：短期均线在长期均线之上（多头排列）且有成交量
        if ma_short > ma_long and avg_volume > 0:
            selected.append(code)

    log.info("")
    if selected:
        log.info("选股结果: %s （共 %d 只）", ", ".join(selected), len(selected))
    else:
        log.info("选股结果: 无符合条件的股票，将使用候选池前 %d 只", MAX_POSITIONS)
        selected = CANDIDATE_STOCKS[:MAX_POSITIONS]

    return selected


# ---------------------------------------------------------------------------
# 阶段 3：建立交易会话
# ---------------------------------------------------------------------------


async def connect_trading(client: AsyncQmtProxyClient) -> str:
    log.info("")
    log.info("=" * 60)
    log.info("阶段 3：建立交易会话")
    log.info("=" * 60)

    resp = await client.trading.connect(account_id=ACCOUNT_ID)
    log.info("连接结果: success=%s | message=%s", resp.success, resp.message)

    if not resp.success or not resp.session_id:
        raise RuntimeError(f"交易连接失败: {resp.message}")

    session_id = resp.session_id
    log.info("会话 ID: %s", session_id)

    # 查询账户资产
    asset = await client.trading.get_asset(session_id)
    log.info(
        "账户资产: 总资产=%.2f | 可用资金=%.2f | 持仓市值=%.2f | 盈亏=%.2f (%.2f%%)",
        asset.total_asset,
        asset.available_cash,
        asset.market_value,
        asset.profit_loss,
        asset.profit_loss_ratio * 100,
    )

    # 查询当前持仓
    positions = await client.trading.get_positions(session_id)
    if positions:
        log.info("当前持仓 (%d 只):", len(positions))
        for pos in positions:
            log.info(
                "  %s %s | 数量=%d | 成本=%.2f | 现价=%.2f | 盈亏=%.2f",
                pos.stock_code,
                pos.stock_name,
                pos.volume,
                pos.cost_price,
                pos.market_price,
                pos.profit_loss,
            )
    else:
        log.info("当前无持仓")

    return session_id


# ---------------------------------------------------------------------------
# 阶段 4 & 5：实时监听 + 交易执行
# ---------------------------------------------------------------------------


async def run_realtime_strategy(
    client: AsyncQmtProxyClient,
    session_id: str,
    targets: list[str],
) -> None:
    log.info("")
    log.info("=" * 60)
    log.info("阶段 4：订阅实时行情 & 执行交易策略")
    log.info("=" * 60)
    log.info(
        "目标股票: %s | 策略: MA%d/MA%d 交叉 | 每笔=%d股 | 最大持仓=%d",
        ", ".join(targets),
        SHORT_MA_PERIOD,
        LONG_MA_PERIOD,
        ORDER_VOLUME,
        MAX_POSITIONS,
    )

    contexts: dict[str, StockContext] = {code: StockContext(code=code) for code in targets}
    tick_count = 0
    trade_count = 0

    log.info("正在建立 WebSocket 连接...")

    stream = client.data.subscribe_and_stream(symbols=targets)
    async with stream:
        log.info("WebSocket 已连接，开始接收实时行情\n")

        async for quote in stream:
            tick_count += 1
            code = quote.stock_code
            if code is None or code not in contexts:
                continue

            ctx = contexts[code]
            price = quote.last_price
            if price is None or price <= 0:
                continue

            ctx.prices.append(price)

            short_ma = calc_ma(ctx.prices, SHORT_MA_PERIOD)
            long_ma = calc_ma(ctx.prices, LONG_MA_PERIOD)

            log.info(
                "[TICK #%04d] %s | 价格=%.2f | 量=%s | "
                "MA%d=%s | MA%d=%s | 持仓=%s",
                tick_count,
                code,
                price,
                quote.volume,
                SHORT_MA_PERIOD,
                f"{short_ma:.2f}" if short_ma else "N/A",
                LONG_MA_PERIOD,
                f"{long_ma:.2f}" if long_ma else "N/A",
                "是" if ctx.held else "否",
            )

            if short_ma is None or long_ma is None:
                log.info(
                    "  → 数据积累中 (%d/%d)，暂不决策",
                    len(ctx.prices),
                    LONG_MA_PERIOD,
                )
                ctx.prev_short_ma = short_ma
                ctx.prev_long_ma = long_ma
                continue

            # 检测金叉 / 死叉
            signal = detect_signal(ctx, short_ma, long_ma)

            if signal == "BUY" and not ctx.held:
                held_count = sum(1 for c in contexts.values() if c.held)
                if held_count >= MAX_POSITIONS:
                    log.info("  → 金叉信号！但已达最大持仓数 %d，跳过", MAX_POSITIONS)
                else:
                    log.info(
                        "  ★ 金叉买入信号！MA%d(%.2f) 上穿 MA%d(%.2f)",
                        SHORT_MA_PERIOD,
                        short_ma,
                        LONG_MA_PERIOD,
                        long_ma,
                    )
                    await execute_buy(client, session_id, ctx, price)
                    trade_count += 1

            elif signal == "SELL" and ctx.held:
                log.info(
                    "  ★ 死叉卖出信号！MA%d(%.2f) 下穿 MA%d(%.2f)",
                    SHORT_MA_PERIOD,
                    short_ma,
                    LONG_MA_PERIOD,
                    long_ma,
                )
                await execute_sell(client, session_id, ctx, price)
                trade_count += 1

            else:
                action = "持仓观望" if ctx.held else "空仓等待"
                log.info("  → %s（无交叉信号）", action)

            ctx.prev_short_ma = short_ma
            ctx.prev_long_ma = long_ma

    log.info("")
    log.info("实时行情流已结束，共处理 %d 个 tick，执行 %d 笔交易", tick_count, trade_count)


def detect_signal(ctx: StockContext, short_ma: float, long_ma: float) -> str:
    """检测均线交叉信号: BUY（金叉）/ SELL（死叉）/ HOLD。"""
    if ctx.prev_short_ma is None or ctx.prev_long_ma is None:
        return "HOLD"

    prev_diff = ctx.prev_short_ma - ctx.prev_long_ma
    curr_diff = short_ma - long_ma

    if prev_diff <= 0 < curr_diff:
        return "BUY"
    if prev_diff >= 0 > curr_diff:
        return "SELL"
    return "HOLD"


async def execute_buy(
    client: AsyncQmtProxyClient,
    session_id: str,
    ctx: StockContext,
    price: float,
) -> None:
    log.info("  → 提交买入委托: %s | 价格=%.2f | 数量=%d", ctx.code, price, ORDER_VOLUME)
    try:
        order = await client.trading.submit_order(
            session_id=session_id,
            stock_code=ctx.code,
            side="BUY",
            volume=ORDER_VOLUME,
            price=price,
            order_type="LIMIT",
            strategy_name="ma_crossover",
        )
        ctx.held = True
        log.info(
            "  ✓ 买入委托已提交 | 订单号=%s | 状态=%s | 时间=%s",
            order.order_id,
            order.status,
            order.submitted_time,
        )
    except QmtProxyError as exc:
        log.error("  ✗ 买入委托失败: %s", exc)


async def execute_sell(
    client: AsyncQmtProxyClient,
    session_id: str,
    ctx: StockContext,
    price: float,
) -> None:
    log.info("  → 提交卖出委托: %s | 价格=%.2f | 数量=%d", ctx.code, price, ORDER_VOLUME)
    try:
        order = await client.trading.submit_order(
            session_id=session_id,
            stock_code=ctx.code,
            side="SELL",
            volume=ORDER_VOLUME,
            price=price,
            order_type="LIMIT",
            strategy_name="ma_crossover",
        )
        ctx.held = False
        log.info(
            "  ✓ 卖出委托已提交 | 订单号=%s | 状态=%s | 时间=%s",
            order.order_id,
            order.status,
            order.submitted_time,
        )
    except QmtProxyError as exc:
        log.error("  ✗ 卖出委托失败: %s", exc)


# ---------------------------------------------------------------------------
# 阶段 6：收尾 — 查询成交 & 断开连接
# ---------------------------------------------------------------------------


async def finalize(client: AsyncQmtProxyClient, session_id: str) -> None:
    log.info("")
    log.info("=" * 60)
    log.info("阶段 5：交易汇总 & 收尾")
    log.info("=" * 60)

    try:
        orders = await client.trading.get_orders(session_id)
        log.info("今日委托 (%d 笔):", len(orders))
        for o in orders:
            log.info(
                "  %s | %s %s | 量=%d | 价=%.2f | 成交量=%d | 状态=%s",
                o.order_id,
                o.side,
                o.stock_code,
                o.volume,
                o.price or 0,
                o.filled_volume,
                o.status,
            )
    except QmtProxyError as exc:
        log.warning("查询委托失败: %s", exc)

    try:
        trades = await client.trading.get_trades(session_id)
        log.info("今日成交 (%d 笔):", len(trades))
        for t in trades:
            log.info(
                "  %s | %s %s | 量=%d | 价=%.2f | 金额=%.2f | 佣金=%.2f",
                t.trade_id,
                t.side,
                t.stock_code,
                t.volume,
                t.price,
                t.amount,
                t.commission,
            )
    except QmtProxyError as exc:
        log.warning("查询成交失败: %s", exc)

    try:
        asset = await client.trading.get_asset(session_id)
        log.info(
            "最终账户: 总资产=%.2f | 可用=%.2f | 持仓市值=%.2f | 盈亏=%.2f",
            asset.total_asset,
            asset.available_cash,
            asset.market_value,
            asset.profit_loss,
        )
    except QmtProxyError as exc:
        log.warning("查询资产失败: %s", exc)

    try:
        await client.trading.disconnect(session_id=session_id)
        log.info("交易会话已断开")
    except QmtProxyError as exc:
        log.warning("断开会话失败: %s", exc)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def main() -> None:
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║       QMT Proxy SDK — 双均线交叉量化交易策略示例        ║")
    log.info("╚══════════════════════════════════════════════════════════╝")
    log.info("服务地址: %s", BASE_URL)
    log.info("交易账户: %s", ACCOUNT_ID)
    log.info(
        "策略参数: MA%d / MA%d | 选股天数=%d | 每笔=%d股 | 最大持仓=%d",
        SHORT_MA_PERIOD,
        LONG_MA_PERIOD,
        SCREENING_DAYS,
        ORDER_VOLUME,
        MAX_POSITIONS,
    )
    log.info("")

    async with AsyncQmtProxyClient(base_url=BASE_URL, api_key=API_KEY) as client:
        # 阶段 1：健康检查
        await check_service(client)

        # 阶段 2：选股
        targets = await screen_stocks(client)

        # 阶段 3：建立交易连接
        session_id = await connect_trading(client)

        # 阶段 4 & 5：实时监听 + 策略执行
        try:
            await run_realtime_strategy(client, session_id, targets)
        except KeyboardInterrupt:
            log.info("\n收到中断信号，正在退出...")
        except QmtProxyError as exc:
            log.error("策略运行异常: %s", exc)
        finally:
            # 阶段 6：收尾
            await finalize(client, session_id)

    log.info("")
    log.info("程序结束")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("用户中断，程序退出")
