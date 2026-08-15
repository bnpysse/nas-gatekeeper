# agy + Neovim (NvChad) Vibe Coding 最佳实践指南

本指南旨在指导您如何将 Google Antigravity 命令行智能体 (**`agy`**) 与 **Neovim (NvChad)** 完美结合，搭建出一套高效、免 API 密钥付费的 **Vibe Coding（双手离开键盘）** 开发环境。

---

## 1. 订阅流免 API 密钥登录机制

由于您是 **Gemini Advanced (Gemini Pro)** 的订阅用户，您**不需要**前往 Google Cloud Console 申请 API Key 或开通结算账户。

### 登录步骤
1. 打开您的 Mac 终端，进入项目目录，直接运行：
   ```bash
   agy
   ```
2. 终端会弹出一个网页浏览器窗口，提示您进行 Google 账户授权。
3. 请选择您**购买了 Gemini Advanced 订阅**的那个 Google 账号进行授权登录。
4. 授权成功后，`agy` 会在本地保存 OAuth 凭证。后续您在终端中与 `agy` 进行的每一次代码重构、询问或指令，都会**自动消耗您订阅内的免费高级算力额度**。

---

## 2. 核心架构：双屏协同与热重载工作流

不要把 `agy` 塞进 Neovim 的小窗口里，最佳的 Vibe Coding 姿势是**分屏（Split Screen）**。

```
+------------------------------------+------------------------------------+
|                                    |                                    |
|         Neovim (NvChad)            |            agy TUI                 |
|                                    |                                    |
|   (左屏：只负责看和微调代码)        |    (右屏：下达宏观指令、跑测试)     |
|                                    |                                    |
|   [src/main.rs]                    |   >>> 帮我把 main 重构为异步...    |
|   async fn main() {                |   [agy] 正在读取 src/main.rs...    |
|       // 👈 看到代码在此处被实时更新  |   [agy] 正在修改文件...            |
|   }                                |   [agy] 正在运行 cargo test...     |
|                                    |                                    |
+------------------------------------+------------------------------------+
```

### 步骤 A：分屏搭建
推荐使用支持原生分屏的终端（如 **Ghostty**, **Alacritty**）或 **tmux**：
- **左边屏**：运行 Neovim 打开代码文件（如 `nvim src/main.rs`）。
- **右边屏**：在项目根目录下运行 `agy` 交互控制台。

### 步骤 B：激活 Neovim 的自动热重载
Neovim 默认支持 `autoread`。当右侧屏的 `agy` 修改了磁盘上的文件时，左侧 Nvim 内的代码会**瞬间无感更新**，您能像看直播一样看到代码变化。

---

## 3. 典型 Vibe Coding 实战流程展示

### 场景：对本地 `nas-gatekeeper` 进行重构

1. **下达任务 (右屏 `agy`)**：
   在 `agy` 控制台中输入：
   > “分析当前项目的 `src/main.rs` 和 `src/config.rs`，将原本阻塞的 HTTP 请求改为基于 `reqwest` 的异步请求，修改完后运行 `cargo check` 验证。”

2. **静静围观 (左屏 `nvim`)**：
   - 此时，您的双手可以离开键盘。
   - `agy` 会通过 Tools 自动读取文件，并向您汇报重构思路。
   - 随后它开始改写。**您会看到左侧 Nvim 里的代码自己动了起来**，新增了 `tokio::main` 和 `async/await` 关键字。

3. **自动化纠错与编译**：
   - `agy` 改完后会在右侧自动执行 `cargo check`。
   - 如果遇到 Rust 编译器的生命周期或类型不匹配报错，它会自动读取报错日志，在右侧分析原因，然后**再次自动修改左侧的代码**，直到通过编译。

4. **一键提交**：
   当编译和测试 100% 通过后，在 `agy` 中输入：
   ```text
   /git commit
   ```
   它会智能归纳刚才重构的全部内容，为您生成符合 Semantic Commits 规范的 Commit Message 并完成本地 Git 提交。

---

## 4. 进阶：配置项目规则矩阵 (Project Rules)

为了防止 `agy` 在自动改写代码时把代码改乱（比如缩进格式不合您意，或者引入不推荐的库），您可以在项目根目录的 `.antigravity/rules/` 下创建规则：

### 编写 [core.md](file:///Users/woodman/dev/nas-gatekeeper/.antigravity/rules/core.md)
```markdown
# 项目代码规范

1. **格式化守卫**：修改任何 Rust 文件后，必须在终端运行 `cargo fmt`。
2. **异步规范**：异步网络请求统一使用 `reqwest::Client`，禁止引入 `ureq` 或其他同步阻塞库。
3. **错误处理**：Rust 中的 Result 必须显式处理，严禁使用 `.unwrap()`，优先使用 `anyhow` 或 `thiserror` 进行错误传播。
```
当 `agy` 启动时，它会自动读取该规则，确保它的“Vibe Coding”动作绝对处于您的规范约束之内。
