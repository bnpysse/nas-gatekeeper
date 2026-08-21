/**
 * 🌐 TokenGate - Cloudflare Worker 极速透明 AI 反向代理
 * 功能：将发往当前 Worker 的请求透明无损转发至 Google Gemini / OpenAI 官方 API
 * 优势：全球 300+ 边缘节点、0 服务器成本、免安装任何代理软件、国内 VPS 毫秒级直通出海
 */

export default {
    async fetch(request, env, ctx) {
        const url = new URL(request.url);

        // 默认目标上游为 Google Gemini API 官方端点
        // 也可通过 Header 或环境变量动态修改
        const targetHost = "generativelanguage.googleapis.com";
        url.host = targetHost;
        url.protocol = "https:";

        // 构建转发请求头部
        const newHeaders = new Headers(request.headers);
        newHeaders.set("Host", targetHost);
        newHeaders.delete("cf-connecting-ip");
        newHeaders.delete("cf-ipcountry");
        newHeaders.delete("cf-ray");
        newHeaders.delete("cf-visitor");

        const newRequest = new Request(url.toString(), {
            method: request.method,
            headers: newHeaders,
            body: request.body,
            redirect: "follow"
        });

        // 转发并返回流式响应
        const response = await fetch(newRequest);
        const responseHeaders = new Headers(response.headers);
        
        // 允许跨域
        responseHeaders.set("Access-Control-Allow-Origin", "*");
        responseHeaders.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
        responseHeaders.set("Access-Control-Allow-Headers", "*");

        if (request.method === "OPTIONS") {
            return new Response(null, { status: 204, headers: responseHeaders });
        }

        return new Response(response.body, {
            status: response.status,
            statusText: response.statusText,
            headers: responseHeaders
        });
    }
};
