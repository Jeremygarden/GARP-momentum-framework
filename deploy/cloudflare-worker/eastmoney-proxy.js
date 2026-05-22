/**
 * Cloudflare Worker: 东财 push2 反向代理
 *
 * 用途：绕过东财对 Azure/云服务器 IP 段（AS8075）的封锁，
 *      将 push2.eastmoney.com 和 push2his.eastmoney.com 的请求
 *      通过 Cloudflare 出口 IP 转发。
 *
 * 部署步骤：
 *   1. 登录 https://dash.cloudflare.com
 *   2. Workers & Pages → Create Worker → 粘贴此文件全部内容
 *   3. 保存并部署，获得 Worker URL（格式：https://xxx.yyy.workers.dev）
 *   4. 将 Worker URL 配置到 data/baostock_financial.py 的 PUSH2_PROXY_BASE
 *
 * 路由规则：
 *   /push2/*      → push2.eastmoney.com/*
 *   /push2his/*   → push2his.eastmoney.com/*
 *
 * 示例：
 *   Worker URL: https://em-proxy.your-name.workers.dev
 *   原始接口:   https://push2his.eastmoney.com/api/qt/stock/kline/get?...
 *   代理接口:   https://em-proxy.your-name.workers.dev/push2his/api/qt/stock/kline/get?...
 */

// 允许的目标域名白名单（防止 Worker 被滥用）
const ALLOWED_TARGETS = {
  "push2": "push2.eastmoney.com",
  "push2his": "push2his.eastmoney.com",
};

// 注入的请求头（模拟浏览器，避免东财识别为非正常请求）
const INJECT_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Referer": "https://quote.eastmoney.com/",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
  "Origin": "https://quote.eastmoney.com",
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 健康检查
    if (url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", ts: Date.now() }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // 解析路径：/push2/api/... 或 /push2his/api/...
    const parts = url.pathname.slice(1).split("/");  // 去掉开头的 /
    const prefix = parts[0];  // "push2" 或 "push2his"

    if (!ALLOWED_TARGETS[prefix]) {
      return new Response(
        JSON.stringify({ error: "invalid prefix", allowed: Object.keys(ALLOWED_TARGETS) }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // 构建目标 URL
    const targetHost = ALLOWED_TARGETS[prefix];
    const targetPath = "/" + parts.slice(1).join("/");  // 去掉 prefix 前缀
    const targetUrl = `https://${targetHost}${targetPath}${url.search}`;

    // 构建转发请求（只保留安全的请求头，注入必要 headers）
    const proxyHeaders = new Headers(INJECT_HEADERS);

    // 透传 Accept-Encoding（让服务端决定压缩方式）
    if (request.headers.get("Accept-Encoding")) {
      proxyHeaders.set("Accept-Encoding", request.headers.get("Accept-Encoding"));
    }

    try {
      const proxyRequest = new Request(targetUrl, {
        method: request.method,
        headers: proxyHeaders,
        // GET 请求不需要 body
        body: request.method !== "GET" && request.method !== "HEAD" ? request.body : null,
        redirect: "follow",
      });

      const response = await fetch(proxyRequest);

      // 构建响应，添加 CORS 头允许跨域（Python requests 不需要但加上无害）
      const respHeaders = new Headers(response.headers);
      respHeaders.set("Access-Control-Allow-Origin", "*");
      respHeaders.set("X-Proxy-Target", targetHost);
      respHeaders.set("X-Proxy-Status", String(response.status));

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: respHeaders,
      });

    } catch (err) {
      return new Response(
        JSON.stringify({ error: "proxy_error", message: err.message, target: targetUrl }),
        { status: 502, headers: { "Content-Type": "application/json" } }
      );
    }
  },
};
