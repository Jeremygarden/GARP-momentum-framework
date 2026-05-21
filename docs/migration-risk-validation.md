# GARP 数据链路迁移风险验证报告（实测）

> 实测环境：Azure / mootdx std / 2026-05-21 UTC

---

### H1 mootdx 前复权
实测结果: 
- `client.bars` 签名：`(symbol='000001', frequency=9, start=0, offset=800, **kwargs)`
- 600519 日K（frequency=4）测试：`adj/fq/autype/fqt/adjustflag/fqtype` 等参数可传但与默认结果**完全一致**（max diff = 0）
- `adjust='qfq'/'hfq'` 触发异常（`NDFrame.fillna()` 参数错误），`adjust='bfq'/'none'` 与默认一致
结论: ❌（mootdx bars 在 std 市场下**不支持前复权**，相关参数无效）
建议操作: 
- 动量因子需前复权时，改用 **baostock**（`adjustflag=2` 前复权）或 **akshare**（`adjust='qfq'`）获取复权价；
- 或另行接入复权因子后自行复权；
- mootdx 仅作为原始价数据源。

---

### H2 新浪三表历史深度
实测结果: 
- 请求利润表接口返回 `__ERROR:3, Service not valid`，JSONP 无法解析
结论: ❌（当前接口不可用，无法验证历史深度）
建议操作: 
- 改用 **东财 datacenter / CNINFO / TuShare** 获取财报序列；
- 需要满足 ≥20 期季报时，优先走有稳定授权的数据源（TuShare Pro/本地财报库）。

---

### H3 Azure → mootdx TCP 连通性
实测结果: 
- `quotes` 延迟约 **64ms**；`bars` 延迟约 **64ms**
- 返回数据正常（600519 近5日日K）
结论: ✅（链路稳定、延迟可接受）
建议操作: 维持现有 mootdx 连接方案。

---

### M1 代码格式转换器
实测结果: 
- 统一转换函数已验证 A股/港股格式：
  - A股：baostock `sh.600519`；mootdx `600519`；腾讯 `sh600519`；yfinance `600519.SS`
  - 港股：腾讯 `hk09992` / `hk00700`；yfinance `9992.HK`
- baostock/mootdx 对港股不支持（显式报错）
结论: ✅
建议操作: 采用以下规则落地转换器：
- A股：6位数字；沪=6开头，深=0/3开头
- 港股：4-5位数字（必要时 zero-pad），仅走腾讯/yfinance

---

### M2 thsdk big_order_flow vs 东财 push2
实测结果: 
- thsdk `THS.big_order_flow()` 需要 10 位 ths_code（如 `USHA600519`）
- 调用返回 `未登录`，无可用数据（需 thsdk 认证）
- 东财 push2 `get_fund_flow_minute()` 正常返回 100 条分钟级资金流字段：`time, main_net_yuan, small_net_yuan, mid_net_yuan, large_net_yuan, super_net_yuan`
结论: ⚠️（thsdk 未鉴权不可用，当前只能依赖东财 push2）
建议操作: 
- 若要保留 thsdk 兜底，需配置 thsdk 认证/登录；
- 否则维持 push2 主链路，thsdk 标注为「停用」。

---

### M3 mootdx 37字段实测
实测结果: 
- `client.finance('600519')` 返回 **37 字段**，列包含：
  `market, code, liutongguben, province, industry, updated_date, ipo_date, ... , jinglirun, weifenpeilirun, meigujingzichan`
结论: ✅
建议操作: 作为轻量财务快照可用；深度财报仍需三表数据源。

---

### L1 东财 reportapi 连通性
实测结果: 
- 研报 API：返回 50 条，最新 2026-05-05
- 财联社快讯：返回 5 条
结论: ✅
建议操作: 维持东财/CLS 直连链路。

---

## 总体结论
- **高风险**：mootdx 无前复权；新浪三表接口失效。
- **中风险**：thsdk 需鉴权，当前不可用。
- **低风险**：东财研报/快讯连通性稳定。

建议优先补齐「复权价」与「财报三表」两条数据链路，以保证 GARP 因子稳定性。
