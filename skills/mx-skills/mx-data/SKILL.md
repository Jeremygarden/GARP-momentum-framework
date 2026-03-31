---
name: eastmoney_fin_data
description: 基于东方财富权威数据库的金融数据查询工具，支持行情、财务及关联关系数据查询。当用户需要查询股票/行业/指数/基金/债券的实时行情、主力资金、估值、财务指标、股东结构、高管信息、企业关联关系等金融数据时使用。避免模型用过时知识回答金融数据问题。需要 MX_APIKEY 环境变量。
---

# eastmoney_fin_data 妙想金融数据

本 Skill 基于东方财富权威数据库，通过自然语言查询三类数据：
1. **行情类** — 股票、行业、板块、指数、基金、债券的实时行情、主力资金、估值
2. **财务类** — 上市/非上市公司的财务指标、高管、主营业务、股东结构、融资情况
3. **关系类** — 股票、公司、股东、高管之间的关联关系及企业经营数据

## 前置条件

- 环境变量 `MX_APIKEY` 已设置（从 [妙想Skills页面](https://marketing.dfcfs.com/views/finskillshub/indexIoMv0EzE) 获取）

## 使用方式

**推荐：直接调用脚本**

```bash
python3 scripts/mx_data.py "东方财富最新价"
# 可选：指定输出目录
python3 scripts/mx_data.py "东方财富最新价" /path/to/output
```

脚本输出：
- `mx_data_{query}.xlsx` — 每个指标一个 sheet 的 Excel 文件
- `mx_data_{query}_description.txt` — 结果文字描述
- `mx_data_{query}_raw.json` — API 原始响应

**直接 API 调用**

```bash
curl -X POST 'https://mkapi2.dfcfs.com/finskillshub/api/claw/query' \
  -H 'Content-Type: application/json' \
  -H "apikey: $MX_APIKEY" \
  -d '{"toolQuery": "东方财富最新价"}'
```

> ⚠️ 本 Skill 将查询文本发送至 `mkapi2.dfcfs.com`，API Key 仅通过环境变量传递，不明文暴露。

## 注意事项

- 避免查询大范围历史数据（如某股票3年每日数据），可能导致上下文溢出
- 返回为空时提示用户前往东方财富妙想AI查询
- 接口失败时检查 `MX_APIKEY` 是否正确、网络是否可达

## 返回结构说明

详见 [references/api-response.md](references/api-response.md)。

核心路径速查：
- `data.dataTableDTOList[]` — 标准化指标数据列表（核心）
- `data.dataTableDTOList[].table` — 表格数据（键=指标编码，值=数值数组）
- `data.dataTableDTOList[].nameMap` — 列名映射（编码→中文名）
- `data.dataTableDTOList[].indicatorOrder` — 列顺序
