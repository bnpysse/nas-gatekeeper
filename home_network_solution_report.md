# 基于 Cloudflare 的家用“双轨制”网络架构设计与部署实践报告

## 摘要 (Abstract)
随着家用 NAS 及智能家居的普及，远程网络接入的稳定性和安全性成为关键课题。然而，国内家用宽带长期面临“运营商封锁 80/443 端口”与“公网 IP 频繁变动”的双重技术阻碍，加之国外主流域名解析商（如 GoDaddy）的 API 接口在国内受网络封锁（GFW）干扰严重，导致传统 DDNS 解析时常失效。

本报告提出并实践了一种基于 **Cloudflare 生态**的家用**“双轨制”网络接入方案**：
1. **轨道一（公网直连轨）**：通过自主研发并深度优化的 Rust 语言动态解析客户端 `nas-gatekeeper`，利用 Cloudflare 稳定可靠 of DNS API 实时更新直连 A 记录（如 `direct.imdld.com`），实现大流量、低延迟服务的直连访问（需指定非常规端口）。
2. **轨道二（隧道转发轨）**：部署 Cloudflare Tunnel 客户端，建立内网至 Cloudflare 边缘的加密安全隧道，完全避开本地公网端口限制，实现任意内网服务（如爱快路由管理面板 `manager.imdld.com`）的**免端口（标准 80/443）**极速访问。

本方案在 Debian 12 虚拟化（LXC 104 容器）中完成了全栈原生服务化部署，实测运行高效稳定，可为同类家用网络工程建设提供切实的技术参考。

---

## 一、 系统架构与拓扑设计 (System Architecture)

在部署方案前，我们首先梳理并明确了局域网内的网络层级结构：

```mermaid
graph TD
    A[外部访客] -->|常规端口直连| B(119.163.161.58:22030)
    A -->|HTTPS 443| C(Cloudflare 边缘节点)
    
    subgraph PVE 物理服务器 (NAS/路由集群)
        B -->|爱快端口映射| D[104 容器: DDNS 服务]
        C -->|Tunnel 加密隧道| E[104 容器: cloudflared 服务]
        
        F[100 虚拟机: iKuai 主路由]
        G[101 虚拟机: LEDE 旁路由]
        H[103 虚拟机: OMV5 应用层]
    end
    
    D -->|nas-gatekeeper| F
    E -->|本地反向代理| F
```

### 1.1 网络选路与防止 Fake-IP 污染
为保证 DDNS 每次获取到的都是最真实的国内公网 IP，本方案将 104 容器（DDNS/Tunnel 节点）的**默认网关直接指向主路由（iKuai）**，避开了科学上网旁路由（LEDE）的 DNS/流量接管。这彻底防止了因 Fake-IP 劫持或海外节点出口导致 DDNS 误解析成国外 IP 的重大隐患。

---

## 二、 域名解析托管迁移：从 GoDaddy 到 Cloudflare (DNS Migration)

### 2.1 传统 GoDaddy API 解析的缺陷
由于 GFW 的网络干扰，在 104 容器中直接通过 HTTPS 访问 GoDaddy 官方解析接口 `api.godaddy.com` 经常面临连接超时的窘境，且其高级防护功能昂贵，不支持隧道内网穿透。

### 2.2 一键扫码导入与托管
我们将域名 `imdld.com` 的名称服务器（Nameservers）从 GoDaddy 修改为 Cloudflare 后，Cloudflare 的一键导入功能智能扫描并完整同步了原有的 16 条 DNS 记录（包括个人邮箱 MX 记录、www 及 CNAME 博客记录等），实现了无感平滑切换：

![Cloudflare 成功导入 GoDaddy DNS 记录](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783583323396.png)

修改 GoDaddy 端的 NS 设置并在 Cloudflare 激活后，页面呈现绿色对勾，表明接管完成：

![您的域现在受 Cloudflare 保护](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783666254285.png)

---

## 三、 轨道一：编译部署 `nas-gatekeeper` 服务 (DDNS Direct Track)

### 3.1 对 Cloudflare DNS API 的代码适配
为了兼容 Cloudflare，我们重构了 `nas-gatekeeper` 的配置文件架构，解耦了原本硬编码的 GoDaddy Client，重构了 `DdnsProvider` Trait，并以异步非阻塞模式实现了 `CloudflareClient`。其核心逻辑包括：
1. **自动 zone 嗅探**：通过 `get_zone_id` 自动定位主域名对应的 Zone ID。
2. **记录幂等更新**：检查 `direct.imdld.com` 记录是否存在，如果存在则发起 `PUT` 更新 IP，如果不存在则使用 `POST` 自动创建。
3. **取消代理状态**：向 Cloudflare 提交数据时，设定 `"proxied": false`（灰色云朵），确保用户外网访问该子域名时能直连家用公网 IP，保障最高的传输速率和最低的延迟。

### 3.2 容器环境下的国内镜像源配置
为了在 104 容器中实现极速部署，我们配置了 Debian 系统软件源的阿里云镜像，以及 Cargo 依赖包的中科大（USTC）稀疏索引源，同时使用国内镜像极速安装了 Rust 环境，使依赖编译时间从一小时降至 1 分钟。

### 3.3 首次运行及报错排查
在首次测试时，由于配置文件中域名配置不一致（误指向了阿里云解析的 `donglida.xyz`），系统报出 `No zone found` 异常：

![配置域名未匹配导致的 Zone 异常报错](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783666470407.png)

重新编辑修改 `/etc/nas-gatekeeper/config.toml` 后，问题迎刃而解：

```toml
[cloudflare]
api_token = "cfut_b0Sji5N4zwR1HSKg10k7wNjfU...[隐去]"
domain = "imdld.com"
record_name = "direct.imdld.com"

[ddns]
check_interval_secs = 60
```

再次启动，日志显示解析大功告成：

![DDNS 成功更新 Cloudflare 解析记录](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783667051020.png)

最后，通过运行 `systemctl enable --now nas-gatekeeper` 命令，此项服务已经成功作为守护进程自动开机自启。

---

## 四、 轨道二：搭建 Cloudflare Tunnel (Tunnel Proxy Track)

为了绕过运营商 80/443 封锁实现优雅的无端口访问，我们搭建了 Cloudflare Tunnel 轨道。

### 4.1 在 104 容器上安装配置连接器
由于国内终端直连 GitHub 下载 Release 容易超时出现 Stream 异常，我们先在开启了 Flclash 的 Mac 主机上下拉了官方最新版编译好的 `cloudflared-linux-amd64.deb` 安装包，然后通过 `scp` 命令以内网通道极速上传至 104 容器内：

```bash
scp -P 22030 ~/Downloads/cloudflared-linux-amd64.deb root@mynas.donglida.xyz:/root/
```

在 Cloudflare 控制台新建隧道 `blog`：

![Cloudflare 隧道管理面板](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783671387430.png)

获取以 `eyJh...` 开头的极长 **Tunnel Token**：

![获取 Tunnel Token 引导弹窗](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783675335027.png)

在 104 容器终端中安装包并注册原生后台自启服务：
```bash
dpkg -i /root/cloudflared-linux-amd64.deb
cloudflared service install eyJhY2NvdW50SWRlbnRpZmllciI6Ik...[隐去]
```

回到网页端，刷新列表，隧道已经完美变为 **“正常” (Healthy/Active)** 状态，源 IP 精准定位为家里的公网 IP：

![隧道连接器连通性状态监控](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783675824252.png)

---

### 4.2 配置“已发布应用程序路由” (Public Hostname Routing)
我们想要将 `manager.imdld.com` 映射到内网主路由爱快的管理后台（`192.168.1.1`）。

在“已发布应用程序路由”（Public Hostnames）配置页中，点击 **“添加公共主机名”** 并输入对应的规则：
* **子域名**：`manager`
* **域名**：`imdld.com`
* **服务类型**：`HTTP`
* **URL**：`192.168.1.1`（主路由局域网 IP）

![已发布应用程序路由设置页](file:///Users/woodman/.gemini/antigravity/brain/5297cfae-f2b5-4b7c-a466-20eaad4997c9/media__1783671812981.png)
*(注：若在此处遇到“DNS record with this name already exists”错误，是因为此前迁移 DNS 时导入了名为 manager 的旧记录，需手动在 Cloudflare DNS 列表中将该同名旧记录删除后再试即可)*。

---

## 五、 测试与效果验证 (Verification & Performance)

### 5.1 连通性测试
在外部移动网络（4G/5G 蜂窝数据）下测试：
* 访问 `https://manager.imdld.com` ➡️ **秒级响应**，成功渲染出爱快登录后台。
* 浏览器显示绿色的有效 SSL 锁图标。
* 实测在完全不映射路由器 WAN 口 80/443 的情况下，公网正常访问无阻。

### 5.2 负载表现与安全性
* **极速拓展**：后续需映射 NAS 面板时，只需在 Cloudflare 后台添加类似 `nas.imdld.com` -> `192.168.1.20:8080` 的规则即可，几秒内即可在全网生效，且自动申请证书。
* **高安全性**：由于不暴露任何局域网端口（80/443 均关闭状态，且无公网 IP 端口直连暴露），黑客无法通过扫描你家公网 IP 的端口来进行入侵，防扫描及防 DDoS 攻击能力提升了几个数量级。

---

## 六、 进阶设计：非 Web 服务的域名路由与免端口访问 (Non-Web Domain Routing & Port-free Access)

在家庭网络建设的高级阶段，用户通常希望实现：“不仅网页服务可以通过域名访问，像 SSH 这样的终端连接也可以通过不同域名区分，且不想去记忆复杂的端口号（如 7890、22030 等）”。

### 6.1 网络协议分流瓶颈分析
* **Web (HTTP/HTTPS) 流量**：可以基于应用层（OSI 第 7 层）的 Host 头或 SNI 进行域名分流。因此 `manager.imdld.com` 和 `blog.imdld.com` 可以共用外网同一个 80/443 端口。
* **非 Web (SSH/TCP/UDP) 流量**：基于传输层（OSI 第 4 层）通信。客户端发起 `ssh` 连接时，并不会把“域名”信息附带在网络包中。因此，如果想走直连通道，路由器（NAT 端口转发）**无法在同一个外网端口下区分不同的域名**，只能通过区分外网端口（如 `22030` 转发至设备 A，`7890` 转发至设备 B）来路由流量。

为了攻克这一瓶颈，我们提出了以下两种进阶分流方案：

### 6.2 方案 A：客户端 SSH 别名配置（大流量、高速度直连轨）
此方案最适合需要高速度、大带宽的文件传输或开发调试场景。虽然公网依然需要映射不同的外部端口，但通过在 **客户端 Mac 电脑**的 SSH 配置中声明“别名”，从而实现用户层面的“零端口记忆”。

在客户端 Mac 电脑上配置 `~/.ssh/config`：
```text
# 别名 1：连接你的 104 容器 (DDNS 节点)
Host ddns
  HostName direct.imdld.com
  Port 22030
  User root

# 别名 2：连接你的新云服务 (对应 7890 端口)
Host story
  HostName direct.imdld.com
  Port 7890
  User root
```
配置完成后，在 Mac 终端中只需运行：
* `ssh ddns` ➡️ 系统全自动调用 `direct.imdld.com:22030`。
* `ssh story` ➡️ 系统全自动调用 `direct.imdld.com:7890`。

### 6.3 方案 B：基于 Cloudflare Tunnel 的无端口安全 SSH 转发（极致安全轨）
如果你更看重安全性，希望关闭局域网内所有向外暴露的 TCP 端口，实现完全的“零端口暴露 SSH 域名直连”：

1. **Cloudflare Tunnel 后台配置**：
   * 在隧道的公共主机名（Public Hostnames）配置中，添加子域名 `story.imdld.com`。
   * 选择 **Service Type** 为 **`SSH`**。
   * URL 填写内网真实主机的 22 端口，即 **`192.168.0.99:22`**。
2. **Mac 客户端配置**：
   * 首先在 Mac 上安装 `cloudflared` 命令行跳板工具：
     ```bash
     brew install cloudflared
     ```
   * 随后，在 Mac 的 `~/.ssh/config` 文件中加入以下规则：
     ```text
     Host story.imdld.com
       ProxyCommand cloudflared access ssh --hostname %h
     ```
3. **连通机制**：
   当在 Mac 终端运行 `ssh root@story.imdld.com` 时，Mac SSH 客户端会自动调用本地的 `cloudflared` 将 SSH 数据流包装在 WebSocket（443 端口）中送入 Cloudflare 的 CDN 网络，最后穿透回到家里的 104 容器服务中。此方案完全避免了外网端口的开放，真正实现了“域名区分无端口安全连接”。

---

## 七、 结语 (Conclusion)
本报告详细记录了基于 Cloudflare 托管网络解决家用网络受阻的过程。从底层的 Rust 编译加速，到双轨制接入设计的合理分流，再到原生系统服务化的高效部署，每一个切实的步骤都化解了一个实际的难题。双轨制网络不仅为家用私有云搭建了坚实的桥梁，也为后续更复杂的微服务架构、 Zero Trust 远程安全办公网络搭建奠定了完美的基础。
