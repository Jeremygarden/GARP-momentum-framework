---
name: eastmoney_self_select
description: 东方财富通行证账户自选股管理工具。当用户需要查询、添加或删除自选股时使用，支持自然语言操作（如"把贵州茅台加入自选"、"删除我的自选股中的宁德时代"、"查看我的自选股列表"）。需要 MX_APIKEY 环境变量。
---

# eastmoney_self_select 妙想自选股管理

通过自然语言查询或操作东方财富通行证账户下的自选股数据。

## 前置条件

- 环境变量 `MX_APIKEY` 已设置（从 [妙想Skills页面](https://marketing.dfcfs.com/views/finskillshub/indexIoMv0EzE) 获取）

## 支持功能

- ✅ 查询自选股列表（含实时行情）
- ✅ 添加股票到自选股
- ✅ 从自选股中删除股票

## 使用方式

**推荐：直接调用脚本**

```bash
# 查询自选股
python3 scripts/mx_self_select.py "查询我的自选股列表"

# 添加股票
python3 scripts/mx_self_select.py "把贵州茅台添加到我的自选股"

# 删除股票
python3 scripts/mx_self_select.py "把宁德时代从自选股删除"
```

**直接 API 调用**

```bash
# 查询
curl -X POST 'https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/get' \
  -H "apikey: $MX_APIKEY" -H 'Content-Type: application/json' -d '{}'

# 添加/删除
curl -X POST 'https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/manage' \
  -H "apikey: $MX_APIKEY" -H 'Content-Type: application/json' \
  -d '{"query": "把贵州茅台添加到我的自选股"}'
```

> ⚠️ 本 Skill 将操作指令发送至 `mkapi2.dfcfs.com`，API Key 仅通过环境变量 `MX_APIKEY` 传递。

## 错误处理

- 未配置 `MX_APIKEY`：提示设置环境变量
- 接口失败：检查 API Key 是否有效、网络是否可达
- 数据为空：提示用户前往东方财富App查询
