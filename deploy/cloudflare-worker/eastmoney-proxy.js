// Cloudflare Worker: 东财 push2 反向代理
// 兼容 Service Worker 格式（无需切换 Module 模式，粘贴即用）
//
// 路由规则：
//   /push2/*    → push2.eastmoney.com/*
//   /push2his/* → push2his.eastmoney.com/*
//   /health     → 健康检查

const ALLOWED_TARGETS = {
  "push2":    "push2.eastmoney.com",
  "push2his": "push2his.eastmoney.com",
};

const INJECT_HEADERS = {
  "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Referer":         "https://quote.eastmoney.com/",
  "Accept":          "application/json, text/plain, */*",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
  "Origin":          "https://quote.eastmoney.com",
};

addEventListener("fetch", function(event) {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  var url = new URL(request.url);

  // 健康检查
  if (url.pathname === "/health") {
    return new Response(
      JSON.stringify({ status: "ok", ts: Date.now() }),
      { headers: { "Content-Type": "application/json" } }
    );
  }

  // 解析前缀：去掉开头的 /，取第一段
  var pathname = url.pathname.slice(1); // 去掉开头 /
  var slashIdx = pathname.indexOf("/");
  var prefix, restPath;

  if (slashIdx === -1) {
    prefix   = pathname;
    restPath = "/";
  } else {
    prefix   = pathname.slice(0, slashIdx);
    restPath = pathname.slice(slashIdx); // 保留开头的 /
  }

  if (!ALLOWED_TARGETS[prefix]) {
    return new Response(
      JSON.stringify({ error: "invalid_prefix", prefix: prefix, allowed: Object.keys(ALLOWED_TARGETS) }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    );
  }

  var targetHost = ALLOWED_TARGETS[prefix];
  var targetUrl  = "https://" + targetHost + restPath + url.search;

  // 构建请求头
  var headers = new Headers();
  for (var key in INJECT_HEADERS) {
    headers.set(key, INJECT_HEADERS[key]);
  }
  var ae = request.headers.get("Accept-Encoding");
  if (ae) { headers.set("Accept-Encoding", ae); }

  try {
    var proxyResp = await fetch(targetUrl, {
      method:   request.method,
      headers:  headers,
      redirect: "follow",
    });

    var respHeaders = new Headers(proxyResp.headers);
    respHeaders.set("Access-Control-Allow-Origin", "*");
    respHeaders.set("X-Proxy-Target", targetHost);

    return new Response(proxyResp.body, {
      status:     proxyResp.status,
      statusText: proxyResp.statusText,
      headers:    respHeaders,
    });

  } catch (err) {
    return new Response(
      JSON.stringify({ error: "proxy_error", message: err.message, target: targetUrl }),
      { status: 502, headers: { "Content-Type": "application/json" } }
    );
  }
}
