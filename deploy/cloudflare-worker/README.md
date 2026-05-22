# Cloudflare Worker 反代部署指南

## 用途

绕过东财对 Azure IP 段（AS8075）的封锁，让 `push2.eastmoney.com` 和
`push2his.eastmoney.com` 的请求通过 Cloudflare 出口 IP 转发。

---

## 部署步骤（5分钟）

### 第一步：创建 Worker

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com)
2. 左侧菜单 → **Workers & Pages** → **Create**
3. 点击 **Create Worker**
4. 给 Worker 取名，例如 `em-proxy`
5. 点击 **Deploy**（先用默认代码部署，下一步再替换）

### 第二步：粘贴 Worker 代码

1. 部署后点击 **Edit Code**
2. **全选删除**编辑器里的默认代码
3. 打开本目录下的 `eastmoney-proxy.js`，**全选复制**
4. 粘贴到编辑器
5. 点击右上角 **Save and Deploy**

### 第三步：获取 Worker URL

部署成功后，页面显示 Worker URL，格式为：
```
https://em-proxy.你的用户名.workers.dev
```

### 第四步：配置环境变量

在运行 GARP 框架的机器上设置环境变量：

```bash
# 临时（当前 shell 生效）
export PUSH2_PROXY_BASE="https://em-proxy.你的用户名.workers.dev"

# 永久（写入 ~/.bashrc 或 ~/.profile）
echo 'export PUSH2_PROXY_BASE="https://em-proxy.你的用户名.workers.dev"' >> ~/.bashrc
source ~/.bashrc
```

### 第五步：验证

```bash
cd ~/.openclaw/workspace-investor

# 验证代理连通性
python3 -c "
import os, requests
base = os.environ.get('PUSH2_PROXY_BASE', '')
print('PUSH2_PROXY_BASE =', base)

# 健康检查
r = requests.get(f'{base}/health', timeout=5)
print('健康检查:', r.json())

# 资金流接口
r = requests.get(
    f'{base}/push2/api/qt/stock/fflow/kline/get',
    params={'secid': '1.600519', 'klt': 1, 'fields1': 'f1,f2,f3,f7', 'fields2': 'f51,f52,f53,f54,f55'},
    timeout=10
)
data = r.json()
klines = data.get('data', {}).get('klines', [])
print(f'资金流分钟数据: {len(klines)} 条')

# 历史K线接口
r = requests.get(
    f'{base}/push2his/api/qt/stock/kline/get',
    params={'secid': '1.600519', 'klt': 101, 'fqt': 1, 'beg': '20260101', 'end': '20991231', 'lmt': 5,
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56'},
    timeout=10
)
data = r.json()
klines = data.get('data', {}).get('klines', [])
print(f'历史K线: {len(klines)} 条')
if klines:
    print('最新一条:', klines[-1][:30])
"
```

---

## 代理路由规则

| 请求路径 | 转发目标 |
|---------|---------|
| `/push2/api/...` | `push2.eastmoney.com/api/...` |
| `/push2his/api/...` | `push2his.eastmoney.com/api/...` |
| `/health` | Worker 健康检查（返回 JSON） |

---

## Cloudflare 免费套餐限制

| 指标 | 免费限额 |
|------|---------|
| 请求数/天 | 100,000 次 |
| CPU 时间/请求 | 10ms |
| 内存 | 128MB |

GARP 框架每次 Phase 2 批处理（426只）约调用 1000 次，每天运行几次完全在免费额度内。

---

## 代码文件

- `eastmoney-proxy.js` — Worker 源码
- 本 `README.md`

## 相关配置

- `data/a_stock_supplement.py` — `PUSH2_PROXY_BASE` + `_push2_url()` / `_push2his_url()`
- `data/baostock_financial.py` — K线改用此代理后可切回东财（可选）
