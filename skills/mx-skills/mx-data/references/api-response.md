# mx-data API 返回字段说明

## 一级路径：`data`

| 字段路径 | 类型 | 说明 |
|---|---|---|
| `data.questionId` | 字符串 | 本次查询唯一标识 |
| `data.dataTableDTOList` | 数组 | 标准化证券指标数据列表，每个元素 = 1个证券 + 1个指标 |
| `data.rawDataTableDTOList` | 数组 | 原始未加工数据，结构同上 |
| `data.condition` | 对象 | 查询条件（关键词、时间范围等） |
| `data.entityTagDTOList` | 数组 | 本次查询涉及证券的去重汇总信息 |

## 二级路径：`data.dataTableDTOList[]`

每个对象 = 证券基础信息 + 表格数据 + 指标元信息 + 证券标签。

### 证券基础信息

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | 字符串 | 证券完整代码（含市场标识，如 300059.SZ） |
| `entityName` | 字符串 | 证券全称（如东方财富 (300059.SZ)） |
| `title` | 字符串 | 本指标数据标题 |

### 表格数据（渲染核心）

| 字段 | 类型 | 说明 |
|---|---|---|
| `table` | 对象 | 标准化表格：键=指标编码，值=指标数值数组；`headName`=时间/维度列 |
| `rawTable` | 对象 | 原始表格，结构同 table，未标准化 |
| `nameMap` | 对象 | 列名映射：指标编码→中文名（如 f2→最新价） |
| `indicatorOrder` | 数组 | 指标列展示顺序（元素为指标编码） |

### 指标元信息：`field`

| 字段 | 类型 | 说明 |
|---|---|---|
| `returnCode` | 字符串 | 指标唯一编码 |
| `returnName` | 字符串 | 指标中文名（如最新价/收盘价） |
| `returnSourceCode` | 字符串 | 底层数据源编码（如 f2/CLOSE） |
| `startDate/endDate` | 字符串 | 查询时间范围 |
| `dateGranularity` | 字符串 | 数据粒度（DAY=日度，MIN=分钟） |

### 证券主体属性：`entityTagDTO`

| 字段 | 类型 | 说明 |
|---|---|---|
| `secuCode` | 字符串 | 证券纯代码（如 300059） |
| `marketChar` | 字符串 | 市场标识（.SZ=深交所，.SH=上交所） |
| `entityTypeName` | 字符串 | 证券类型（A股/港股/债券） |
| `fullName` | 字符串 | 证券完整中文名 |
| `entityId` | 字符串 | 系统内唯一主体 ID |

## 查询条件：`data.condition`

| 字段 | 说明 |
|---|---|
| `condition.search_data_task_0` | 原始查询条件数组（证券名+指标名+时间范围） |
