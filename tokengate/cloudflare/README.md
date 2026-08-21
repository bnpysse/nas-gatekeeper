# 🌐 Cloudflare Worker AI 极速反代部署指南

针对国内服务器（如阿里云、腾讯云、华为云等）无法直接访问 Google Gemini API 的问题，只需在 Cloudflare 上免费部署一个轻量 Worker，即可实现国内主机 0 成本、免代理、毫秒级直通 Gemini！

---

## ⚡ 极速部署步骤 (只需 1 分钟)

1. 登录 [Cloudflare 控制台](https://dash.cloudflare.com)；
2. 在左侧菜单点击 **Workers & Pages** ➔ **创建应用程序 (Create Application)** ➔ **创建 Worker (Create Worker)**；
3. 将名称设为 `tokengate-gemini-proxy`，点击 **部署**；
4. 点击 **编辑代码 (Edit Code)**，将 `cloudflare/worker.js` 中的全部代码粘贴替换进去，点击 **保存并部署 (Save and Deploy)**；
5. （可选推荐）绑定您的自定义域名：
   - 进入该 Worker 详情页 ➔ **Settings (设置)** ➔ **Triggers (触发器)** ➔ **Custom Domains (自定义域)**；
   - 添加自定义域名，如 `gemini.yourdomain.xyz`。

---

## 🚀 在 TokenGate 中使用

在 `.env` 文件中设置：
```bash
GEMINI_API_KEY=AIzaSy...
GEMINI_BASE_URL=https://gemini.yourdomain.xyz
```
国内服务器即可畅通无阻使用 Google Gemini 1500 次/天的免费超大模型！
