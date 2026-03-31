# 模拟交易接口详细说明

所有接口均使用 `POST`，`Content-Type: application/json`，Header 携带 `apikey: $MX_APIKEY`。
基础地址：`$MX_API_URL`（默认 `https://mkapi2.dfcfs.com/finskillshub`）

---

## 1. 持仓查询 `POST /api/claw/mockTrading/positions`

请求体：`{"moneyUnit": 1}`

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `totalAssets` | Int64 | 总资产（元） |
| `availBalance` | Int64 | 可用余额（元） |
| `totalPosValue` | Int64 | 总持仓市值（元） |
| `posCount` | Int32 | 持仓股票数量 |
| `totalProfit` | Int64 | 总盈亏（元） |
| `posList[]` | Array | 持仓明细列表 |

`posList` 元素：

| 字段 | 类型 | 说明 |
|---|---|---|
| `secCode` | String | 证券代码 |
| `secName` | String | 证券名称 |
| `secMkt` | Int32 | 市场：0=深交所，1=上交所 |
| `count` | Int64 | 持仓数量（股） |
| `availCount` | Int64 | 可用数量（股） |
| `value` | Int64 | 市值（元） |
| `costPrice` | Int64 | 成本价（整数，还原：costPrice / 10^costPriceDec） |
| `price` | Int64 | 现价（整数，还原：price / 10^priceDec） |
| `dayProfit` | Int64 | 当日盈亏（元） |
| `dayProfitPct` | Double | 当日盈亏比例(%) |
| `profit` | Int64 | 持仓盈亏（元） |
| `profitPct` | Double | 持仓盈亏比例(%) |

---

## 2. 买入/卖出 `POST /api/claw/mockTrading/trade`

请求体参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | `buy`=买入，`sell`=卖出 |
| `stockCode` | 是 | 6位股票代码（仅A股） |
| `price` | 条件必填 | 委托价格（`useMarketPrice=false` 时必填） |
| `quantity` | 是 | 委托数量（必须为100的整数倍） |
| `useMarketPrice` | 否 | `true`=以最新价委托，忽略 price 参数 |

**价格规则**：沪市小数位≤2位，深市≤3位。

---

## 3. 撤单 `POST /api/claw/mockTrading/cancel`

请求体参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | `order`=撤指定委托，`all`=一键撤单 |
| `orderId` | 条件必填 | 委托编号（type=order 时必填） |
| `stockCode` | 条件必填 | 股票代码（type=order 时必填） |

---

## 4. 委托查询 `POST /api/claw/mockTrading/orders`

请求体参数：

| 参数 | 说明 |
|---|---|
| `fltOrderDrt` | 0=全部，1=买入，2=卖出 |
| `fltOrderStatus` | 0=全部，2=已报，4=已成 |

委托状态 `status`：1=未报，2=已报，3=部成，4=已成，5=部成待撤，6=已报待撤，7=部撤，8=已撤，9=废单，10=撤单失败

委托列表 `orders[]` 核心字段：

| 字段 | 说明 |
|---|---|
| `id` | 委托单ID |
| `secCode` | 证券代码 |
| `secName` | 证券名称 |
| `drt` | 方向：1=买，2=卖 |
| `price` | 委托价（整数，还原：price / 10^priceDec） |
| `count` | 委托数量 |
| `tradeCount` | 成交数量 |
| `status` | 委托状态（见上表） |
| `time` | 委托时间（Unix时间戳） |

---

## 5. 资金查询 `POST /api/claw/mockTrading/balance`

请求体：`{"moneyUnit": 1}`

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `totalAssets` | Int64 | 总资产（元） |
| `availBalance` | Int64 | 可用余额（元） |
| `frozenMoney` | Int64 | 冻结金额（元） |
| `totalPosValue` | Int64 | 总持仓市值（元） |
| `totalPosPct` | Double | 总持仓仓位(%) |
| `nav` | Double | 单位净值 |
| `initMoney` | Int64 | 初始资金（元） |

---

## 错误码

| 错误码 | 含义 | 处理方式 |
|---|---|---|
| 113 | 今日调用次数已达上限 | 提示前往妙想Skills页面获取更多次数 |
| 114 | API密钥不存在或已失效 | 提示更新 `MX_APIKEY` |
| 115 | 请求未携带API密钥 | 检查 `MX_APIKEY` 是否配置 |
| 116 | API密钥不存在 | 检查 `MX_APIKEY` 是否正确 |
| 404 | 未绑定模拟组合账户 | 引导用户前往 [妙想Skills页面](https://dl.dfcfs.com/m/itc4) 创建并绑定账户 |
