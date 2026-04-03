# QMT Proxy — HTTP / WebSocket API 参考

本文档描述本仓库 **REST API** 与 **WebSocket** 契约，供独立维护的 **SDK 仓库** 对齐实现与回归测试。本文 **不包含 gRPC**。

**权威来源（代码）**：`app/routers/data.py`、`app/routers/trading.py`、`app/routers/health.py`、`app/routers/websocket.py`、`app/models/data_models.py`、`app/models/trading_models.py`、`app/dependencies.py`、`app/utils/helpers.py`。

**变更约定**：新增或修改路由时，应同步更新本文档；OpenAPI 见运行实例的 `/docs` 与 `/redoc`（字段级 schema 以 Pydantic 模型为准）。

---

## 1. 基础约定

### 1.1 Base URL

服务默认监听配置见 `config.yml` / 环境变量（`AppConfig.host`、`AppConfig.port`，常见为 `http://<host>:8000`）。下文路径均为相对路径。

### 1.2 内容类型

- 请求/响应 JSON：`Content-Type: application/json`（`GET` 无 body 除外）。
- WebSocket：文本帧中承载 **UTF-8 JSON** 字符串（见第 4 节）。

### 1.3 认证（REST）

受保护接口通过 FastAPI `HTTPBearer` 读取令牌：

| 方式 | 说明 |
|------|------|
| `Authorization: Bearer <api_key>` | **当前实现使用的唯一方式** |

密钥白名单来自配置 `security.api_keys`（见 `app/dependencies.verify_api_key`）。

> **说明**：`config.yml` 中存在 `security.api_key_header`（如 `X-API-Key`）字段，但 **`verify_api_key` 未读取该请求头**；SDK 应以 **`Authorization: Bearer`** 为准。若未来服务端增加 `X-API-Key` 支持，需同时改 `app/dependencies.py` 并修订本文档。

**无需 API Key 的 HTTP 接口**：`GET /`、`GET /info`、`GET /health/*`、`GET /ws/test`、`GET /ui/*`（静态 Web UI）。

**WebSocket**：当前 `GET /ws/quote/{subscription_id}` **未校验** API Key（仅校验订阅是否存在）。部署在公网时需由网关或后续版本补强认证。

### 1.4 响应体两种形态

1. **包装格式**（`format_response`）  
   典型字段：

   ```json
   {
     "success": true,
     "message": "…",
     "code": 200,
     "timestamp": "2026-04-03T12:00:00.000000",
     "data": { }
   }
   ```

   `data` 可省略（例如 `data: null`）。错误时常见 `success: false`，`code` 与 HTTP 状态码常与业务一致（视具体处理器而定）。

2. **裸模型 JSON**（FastAPI `response_model` 直接序列化）  
   响应体即为 Pydantic 模型对应的 JSON **对象或数组**，**没有**外层的 `success` / `code` / `data` 包装。  
   例如：`POST /api/v1/data/market` 返回 `MarketDataResponse[]`。

SDK 应对 **Content-Type: application/json** 先做结构探测：若存在顶层 `success` 字段，按包装格式解析；否则按具体接口约定的模型解析。

### 1.5 错误与 HTTP 状态码

- 路由内显式 `HTTPException`：由 `app/main.py` 中 `http_exception_handler` 转为 JSON，`message` 常为 `str(exc.detail)`（若 `detail` 为 dict，可能被字符串化）。
- `DataServiceException` / `TradingServiceException` 等经 `handle_xtquant_exception` 映射为 `HTTPException` 时，`detail` 常含 `message`、`error_code`。
- 任意 `XTQuantException`（含 `AuthenticationException`）若未被转换为 `HTTPException` 而向上抛出，会被 `xtquant_exception_handler` 捕获并以 **HTTP 500** 返回包装格式 JSON（以当前 `app/main.py` 为准）。**SDK 应对 5xx 同样解析 `message`。**

---

## 2. 系统与元数据

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `GET` | `/` | 否 | 欢迎信息、`docs_url`、`redoc_url`、`xtquant_mode` 等（包装格式） |
| `GET` | `/info` | 否 | 应用名、版本、监听信息、`xtquant_mode`、`allow_real_trading` 等（包装格式） |

---

## 3. 健康检查

前缀：`/health`（包装格式）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health/` | 综合健康信息（注意：代码中 `timestamp` 为固定占位字符串） |
| `GET` | `/health/ready` | 就绪 |
| `GET` | `/health/live` | 存活 |

---

## 4. WebSocket — 行情推送

### 4.1 连接 URL

```
ws://<host>:<port>/ws/quote/{subscription_id}
wss://<host>:<port>/ws/quote/{subscription_id}
```

`subscription_id` 由 `POST /api/v1/data/subscription` 返回。

### 4.2 行为概要

1. 服务端 `accept` 后根据 `subscription_id` 查询订阅；若不存在，发送一条 JSON 错误消息后关闭连接（close code **1008**）。
2. 若存在，先发一条 **`connected`** 消息。
3. 随后持续推送 **`quote`** 消息；`data` 来自 xtquant 回调，一般为 **按合约代码分组的字典结构**（具体字段与周期、品种有关，SDK 宜按动态字典处理）。
4. 客户端可发送 **文本帧**，内容为 JSON：`{"type":"ping"}` → 服务端回复 `{"type":"pong","timestamp":"…"}`。

### 4.3 服务端 → 客户端消息类型

| `type` | 说明 | 典型字段 |
|--------|------|----------|
| `connected` | 订阅通道就绪 | `subscription_id`, `message`, `timestamp` |
| `quote` | 行情推送 | `data`（对象，xtquant 原始结构）, `timestamp` |
| `pong` | 心跳响应 | `timestamp` |
| `error` | 错误 | `message` |

### 4.4 客户端 → 服务端

| `type` | body 示例 | 说明 |
|--------|-----------|------|
| `ping` | `{"type":"ping"}` | 心跳（需可 `json.loads` 的文本帧） |

### 4.5 辅助 HTTP

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/ws/test` | 简易 HTML 测试页（不含 API Key） |

---

## 5. 数据服务 REST API

**前缀**：`/api/v1/data`  
**认证**：除另有说明外均为 `Authorization: Bearer <api_key>`。

### 5.1 枚举与周期（摘录）

**`PeriodType`**（`app/models/data_models.py`）：`tick`, `1m`, `5m`, `15m`, `30m`, `1h`, `1d`, `1w`, `1mon`, `1q`, `1hy`, `1y`。

**订阅 `adjust_type`**：`none` | `front` | `back` | `front_ratio` | `back_ratio`。

**`SubscriptionType`**：`quote`（指定代码订阅）、`whole_quote`（全推，受配置 `whole_quote_enabled` 等约束）。

---

### 5.2 行情与财务（裸模型响应）

| 方法 | 路径 | 请求体模型 | 响应 |
|------|------|------------|------|
| `POST` | `/market` | `MarketDataRequest` | `MarketDataResponse[]` |
| `POST` | `/financial` | `FinancialDataRequest` | `FinancialDataResponse[]` |
| `GET` | `/sectors` | — | `SectorResponse[]` |
| `POST` | `/index-weight` | `IndexWeightRequest` | `IndexWeightResponse` |
| `GET` | `/trading-calendar/{year}` | — | `TradingCalendarResponse` |
| `GET` | `/instrument/{stock_code}` | — | `InstrumentInfo` |
| `GET` | `/etf/{etf_code}` | — | `ETFInfoResponse`（当前路由为占位实现） |

**`POST /sector`**：`SectorRequest` → **包装格式**；若板块名匹配 `GET /sectors` 中某项，则 `data` 为该板块序列化；否则 `data` 为 `{"sector_name","stock_list":[]}`。

---

### 5.3 基础信息（包装格式 `data`）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/instrument-type/{stock_code}` | 合约类型 |
| `GET` | `/holidays` | 节假日列表 |
| `GET` | `/convertible-bonds` | 可转债信息 |
| `GET` | `/ipo-info` | 新股申购信息 |
| `GET` | `/period-list` | 可用 K 线周期列表 |
| `GET` | `/data-dir` | 本地数据目录 |

---

### 5.4 行情数据（包装格式）

| 方法 | 路径 | 请求体 |
|------|------|--------|
| `POST` | `/local-data` | `LocalDataRequest` |
| `POST` | `/full-tick` | `FullTickRequest` |
| `POST` | `/divid-factors` | `DividFactorsRequest`（使用 `stock_code`） |
| `POST` | `/full-kline` | `FullKlineRequest` |

---

### 5.5 数据下载任务（包装格式）

均返回服务端任务提交结果（具体 `data` 结构以 `DataService` 返回为准，模型见 `DownloadResponse` 等）。

| 方法 | 路径 | 请求体 |
|------|------|--------|
| `POST` | `/download/history-data` | `DownloadHistoryDataRequest` |
| `POST` | `/download/history-data-batch` | `DownloadHistoryDataBatchRequest` |
| `POST` | `/download/financial-data` | `DownloadFinancialDataRequest` |
| `POST` | `/download/financial-data-batch` | `DownloadFinancialDataBatchRequest` |
| `POST` | `/download/sector-data` | — |
| `POST` | `/download/index-weight` | `DownloadIndexWeightRequest` |
| `POST` | `/download/cb-data` | — |
| `POST` | `/download/etf-info` | — |
| `POST` | `/download/holiday-data` | — |
| `POST` | `/download/history-contracts` | `DownloadHistoryContractsRequest` |

---

### 5.6 板块管理（包装格式）

| 方法 | 路径 | 参数 / Body |
|------|------|-------------|
| `POST` | `/sector/create-folder` | Query：`parent_node`（默认 `""`）, `folder_name`（默认 `""`） |
| `POST` | `/sector/create` | JSON：`parent_node`, `sector_name`, `overwrite`（可选，默认 `true`） |
| `POST` | `/sector/add-stocks` | JSON：`sector_name`, `stock_list` |
| `POST` | `/sector/remove-stocks` | JSON：`sector_name`, `stock_list` |
| `POST` | `/sector/remove` | Query：`sector_name`（**注意**：该路由为 `POST`，名称为 query 参数） |
| `POST` | `/sector/reset` | JSON：`sector_name`, `stock_list` |

---

### 5.7 Level2（包装格式）

| 方法 | 路径 | 请求体 |
|------|------|--------|
| `POST` | `/l2/quote` | `L2QuoteRequest` |
| `POST` | `/l2/order` | `L2OrderRequest` |
| `POST` | `/l2/transaction` | `L2TransactionRequest` |

---

### 5.8 行情订阅与列表

| 方法 | 路径 | 请求体 / 说明 | 响应 |
|------|------|---------------|------|
| `POST` | `/subscription` | `SubscriptionRequest` | **JSON 对象**（非 `format_response`）：含 `subscription_id`, `status`, `created_at`, `symbols`, `period`, `start_date`, `adjust_type`, `subscription_type`, `message` |
| `DELETE` | `/subscription/{subscription_id}` | — | `success`, `message`, `subscription_id` |
| `GET` | `/subscription/{subscription_id}` | — | 订阅详情对象；不存在时 **404** |
| `GET` | `/subscriptions` | — | `subscriptions`（数组）, `total` |

**`GET /subscription/{id}` 返回字段**（与 `SubscriptionManager.get_subscription_info` 一致）：

- `subscription_id`, `subids_xtquant`, `symbols`, `period`, `start_date`, `adjust_type`, `subscription_type`
- `created_at`, `last_heartbeat`（ISO 时间字符串）
- `active`, `queue_size`

---

## 6. 交易服务 REST API

**前缀**：`/api/v1/trading`  
**认证**：`Authorization: Bearer <api_key>`

| 方法 | 路径 | 请求体 | 响应形态 |
|------|------|--------|----------|
| `POST` | `/connect` | `ConnectRequest` | `ConnectResponse`（裸模型） |
| `POST` | `/disconnect/{session_id}` | — | 包装格式，`data.success` |
| `GET` | `/account/{session_id}` | — | `AccountInfo` |
| `GET` | `/positions/{session_id}` | — | `PositionInfo[]` |
| `POST` | `/order/{session_id}` | `OrderRequest` | `OrderResponse` |
| `POST` | `/cancel/{session_id}` | `CancelOrderRequest` | 包装格式，`data.success` |
| `GET` | `/orders/{session_id}` | — | `OrderResponse[]` |
| `GET` | `/trades/{session_id}` | — | `TradeInfo[]` |
| `GET` | `/asset/{session_id}` | — | `AssetInfo` |
| `GET` | `/risk/{session_id}` | — | `RiskInfo` |
| `GET` | `/strategies/{session_id}` | — | `StrategyInfo[]` |
| `GET` | `/status/{session_id}` | — | 包装格式，`data.connected` |

### 6.1 交易相关枚举（`trading_models`）

- **`AccountType`**：`FUTURE`, `SECURITY`, `CREDIT`, `FUTURE_OPTION`, `STOCK_OPTION`, `HUGANGTONG`, `INCOME_SWAP`, `NEW3BOARD`, `SHENGANGTONG`
- **`OrderSide`**：`BUY`, `SELL`
- **`OrderType`**：`MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`
- **`OrderStatus`**：`PENDING`, `SUBMITTED`, `PARTIAL_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`

时间字段在 JSON 中一般为 ISO 8601 字符串（`datetime` 序列化）。

---

## 7. 请求模型字段参考（SDK 生成类型时可对照）

下列模型定义于 `app/models/data_models.py`（数据）与 `app/models/trading_models.py`（交易）。仅列核心字段；完整校验规则以代码为准。

### 7.1 `MarketDataRequest`（继承 `DataRequest`）

- `stock_codes: string[]`（必填）
- `start_date`, `end_date: string` — `""` 或 `YYYYMMDD` / `YYYYMMDDHHMMSS` 数字串
- `period: PeriodType`
- `fields?: string[]`
- `adjust_type?: string`（默认 `"none"`）
- `fill_data: bool`（默认 `true`）
- `disable_download: bool`（默认 `false`）

### 7.2 `FinancialDataRequest`

- `stock_codes`, `table_list: string[]`
- `start_date?`, `end_date?`

### 7.3 `SubscriptionRequest`

- `symbols: string[]`（非空，去空白）
- `period: PeriodType`（默认 `tick`）
- `start_date: string`
- `adjust_type: string`
- `subscription_type: SubscriptionType`

### 7.4 `ConnectRequest`

- `account_id: string`
- `password?: string`
- `client_id?: number`

### 7.5 `OrderRequest`

- `stock_code`, `side`, `order_type`, `volume`；`price?`, `strategy_name?`

### 7.6 `CancelOrderRequest`

- `order_id: string`

---

## 8. SDK 维护清单（建议）

1. **认证头**：统一使用 `Authorization: Bearer`；集成测试与配置中的 key 列表对齐。
2. **双响应形态**：对每条接口固定判断是否为包装响应，避免硬编码全局反序列化。
3. **WebSocket**：实现 `connected` / `quote` / `pong` / `error` 分支；`quote.data` 按动态结构处理。
4. **版本漂移**：发版前 diff `app/routers/*.py` 与本文档；必要时补充示例 JSON。
5. **OpenAPI**：运行时 `GET /openapi.json` 可辅助生成客户端，但与本文档冲突时 **以本仓库路由实现为准**（OpenAPI 可能未覆盖 `dict`/`Any` 的细粒度结构）。

---

## 9. 文档版本

| 日期 | 说明 |
|------|------|
| 2026-04-03 | 初版：基于当前 `app/routers` 与模型整理，范围 REST + WebSocket，不含 gRPC。 |
