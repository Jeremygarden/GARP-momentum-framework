---
name: eastmoney_stock_simulator
description: 东方财富妙想股票模拟组合管理工具，提供完整的模拟炒股体验。当用户需要模拟交易练手、验证策略时使用，支持：查询持仓、买入/卖出股票、撤单、查询委托记录、查询资金余额等操作。仅支持A股模拟交易，不适用于真实交易、投资建议或非A股品种。需要 MX_APIKEY 环境变量和妙想平台模拟账户。
---

# eastmoney_stock_simulator 妙想模拟组合管理

股票模拟组合管理系统，支持完整的模拟交易流程。所有操作均通过安全认证的API接口完成。

## 前置条件

1. 环境变量 `MX_APIKEY` 已设置
2. 已在 [妙想Skills页面](https://dl.dfcfs.com/m/itc4) 创建模拟账户并绑定模拟组合
3. `curl` 和 `jq` 可用

环境变量：
- `MX_APIKEY`：API密钥（必填）
- `MX_API_URL`：API基础地址（可选，默认 `https://mkapi2.dfcfs.com/finskillshub`）

## 支持功能

| 功能 | 触发词示例 | 接口路径 |
|---|---|---|
| 持仓查询 | 查询持仓、我的持仓 | `POST /api/claw/mockTrading/positions` |
| 买入/卖出 | 买入、卖出、buy、sell | `POST /api/claw/mockTrading/trade` |
| 撤单 | 撤单、一键撤单、cancel | `POST /api/claw/mockTrading/cancel` |
| 委托查询 | 查询委托、历史成交 | `POST /api/claw/mockTrading/orders` |
| 资金查询 | 查询资金、账户余额 | `POST /api/claw/mockTrading/balance` |

## 使用方式

**推荐：直接调用脚本**

```bash
python3 scripts/mx_stock_simulator.py "查询我的持仓"
python3 scripts/mx_stock_simulator.py "买入100股贵州茅台"
python3 scripts/mx_stock_simulator.py "查询我的资金"
```

**直接 API 调用示例（持仓查询）**

```bash
curl -X POST "$MX_API_URL/api/claw/mockTrading/positions" \
  -H "apikey: $MX_APIKEY" \
  -H "Content-Type: application/json" \
  -d '{"moneyUnit": 1}'
```

> ⚠️ 本 Skill 将操作指令发送至 `mkapi2.dfcfs.com`，API Key 仅通过环境变量传递，不明文暴露。

## 股票代码规则

- 仅支持A股，格式为6位数字（如 `600519`、`000001`）
- 系统自动识别并补全市场号（沪/深）
- 委托数量必须为 **100的整数倍**

## 接口详情与错误码

详见 [references/api-reference.md](references/api-reference.md)。
