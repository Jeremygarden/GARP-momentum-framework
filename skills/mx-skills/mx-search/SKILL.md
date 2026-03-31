---
name: eastmoney_fin_search
description: 基于东方财富妙想搜索能力的金融资讯查询工具，对金融场景进行信源智能筛选。当用户需要查询时效性信息或特定事件时使用，包括：个股/板块新闻、公告、研报、政策解读、市场异动原因、宏观影响分析、交易规则等需要检索外部权威信息的任务。避免AI引用过时或非权威金融信息。需要 MX_APIKEY 环境变量。
---

# eastmoney_fin_search 妙想资讯搜索

本 Skill 基于东方财富妙想搜索能力，对金融场景进行信源智能筛选，获取新闻、公告、研报、政策、市场事件等实时资讯。

## 前置条件

- 环境变量 `MX_APIKEY` 已设置（从 [妙想Skills页面](https://marketing.dfcfs.com/views/finskillshub/indexIoMv0EzE) 获取）

## 使用方式

**推荐：直接调用脚本**

```bash
python3 scripts/mx_search.py "立讯精密最新研报"
# 可选：指定输出目录
python3 scripts/mx_search.py "立讯精密最新研报" /path/to/output
```

脚本输出：
- `mx_search_{query}.txt` — 提取后的纯文本结果
- `mx_search_{query}.json` — API 原始响应

**直接 API 调用**

```bash
curl -X POST 'https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search' \
  -H 'Content-Type: application/json' \
  -H "apikey: $MX_APIKEY" \
  -d '{"query": "立讯精密的资讯"}'
```

> ⚠️ 本 Skill 将查询文本发送至 `mkapi2.dfcfs.com`，API Key 仅通过环境变量传递。

## 适用问句示例

| 类型 | 示例 |
|---|---|
| 个股资讯 | 格力电器最新研报、贵州茅台机构观点 |
| 板块/主题 | 商业航天板块近期新闻、新能源政策解读 |
| 宏观/风险 | 美联储加息对A股影响、汇率风险对冲分析 |
| 市场解读 | 今日大盘异动原因、北向资金流向解读 |

## 返回字段速查

| 字段 | 说明 |
|---|---|
| `title` | 资讯标题 |
| `trunk` | 核心正文/结构化数据 |
| `secuList[].secuCode` | 关联证券代码 |
| `secuList[].secuName` | 关联证券名称 |
