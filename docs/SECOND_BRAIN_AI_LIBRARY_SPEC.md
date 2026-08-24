# 第二大脑·AI 智能图书馆与精读研习闭环系统实施方案

## 1. 系统愿景与目标

将统帅保存在 Google Drive 及本地的浩瀚电子书资产，通过 **TokenGate 免费算力网关** 与 **Turso 统一边缘向量库**，转化为随身可用、深度掌握的「第二大脑智能图书馆」与「精读研习工作流」。

### 核心交付价值：
1. **🔍 3分钟极简透视**：一句话主旨、全书知识树脉络（Mermaid）、3~5 个颠覆性洞见（Key Takeaways）；
2. **📖 20%~25% 精华干货缩减本**：利用 Gemini 100万 Token 超大上下文通读全书，去水留精，去重复、留论据，半小时吃透原著；
3. **🎯 交互式研习测试题库**：DeepSeek-V4-Pro 命制客观选择题与场景实战题，精准锚定原书章节页码出处与深度题解；
4. **🎙️ 双人对谈听书音频**：将缩减本改编为趣味双人播客对谈剧本，通过自然语音合成（TTS）输出双人对谈音频，通勤散步随时听书；
5. **🧠 概念记忆闪卡 (Anki / 艾宾浩斯)**：提炼核心概念 Q&A 卡片，利用碎片时间间隔重复记忆；
6. **📱 双端交互体验**：
   - **Web 端 (Quartz 5 数字花园)**：精美排版阅读、内嵌 HTML5 音频播放器、折叠式答题卡片；
   - **随身端 (Telegram Bot)**：手机随时随地点击 Inline 按键交互做题、即时判分、推送听书音频。

---

## 2. 总体架构与技术选型

```
                       📚 Google Drive 电子书 (PDF / EPUB / MOBI / TXT)
                                            │
                                 [rclone 定时同步 / TG 发送]
                                            │
                                ┌───────────┴───────────┐
                                ▼                       ▼
                         [文本与目录结构提取]      [章节语义切块]
                                │                       │
                   [Gemini 100万长窗口全局吞吐]  [Qwen3-VL 2560维向量]
                                │                       │
            ┌───────────────────┼───────────────────┐   ▼
            ▼                   ▼                   ▼ [Turso 边缘向量库]
    ① 20% 精华缩减本    ② 章节研习测试题库    ③ 双人播客剧本    ▲
            │                   │                   │        │ (语义召回+重排)
            │                   ▼                   ▼        │
            │           [TG Bot 交互按键做题]   [TTS 语音合成] [Qwen3-VL-Rerank]
            │                   │                   │        │
            └───────────────────┼───────────────────┘        ▼
                                ▼                    [DeepSeek-V4-Pro]
                     [Quartz 5 网页精读书房]           (复杂研讨与题解)
```

### 核心技术栈：
- **算力调度**：TokenGate 网关 (`https://tg.donglida.com/v1`)
  - **长文本通读**：`Gemini 2.5 Flash / 3.7 Flash`（100万 Tokens 上下文，每日 1500 次免费循环）
  - **试题命制与逻辑题解**：`DeepSeek-V4-Pro`（火山方舟 200万 Tokens/天 循环保底）
  - **向量与重排**：`Qwen3-VL-Embedding` (2560 维高精) + `Qwen3-VL-Rerank`
- **存储与索引**：`Turso (libSQL)` 统一向量数据库（文章、音视频、电子书全域打通，拒绝数据孤岛）
- **语音合成**：`Edge-TTS` / `CosyVoice` 自然中文多角色声线（男女双人对谈）
- **文件与笔记同步**：`rclone` + `Obsidian` 笔记标准 + `Quartz 5` 数字花园

---

## 3. 数据模型设计 (Turso 数据库规范)

统一扩展 N100 现有的 Turso 数据库：

```sql
-- 1. 书籍主表
CREATE TABLE IF NOT EXISTS library_books (
    id TEXT PRIMARY KEY,               -- UUID / 规范书名hash
    title TEXT NOT NULL,              -- 书籍全称
    author TEXT,                      -- 作者
    category TEXT,                    -- 分类 (投资理财, 技术架构, 认知哲学, 历史人文)
    total_words INTEGER,              -- 原始总字数
    summary_3min TEXT,                -- 3分钟极简透视 (Markdown)
    key_takeaways TEXT,               -- 核心颠覆性洞见 (JSON)
    condensed_content TEXT,           -- 20% 精华缩减本 (Markdown)
    podcast_audio_path TEXT,          -- 生成的双人对谈音频文件路径
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 章节切块与 2560 维向量索引
CREATE TABLE IF NOT EXISTS library_chapters (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES library_books(id),
    chapter_index INTEGER NOT NULL,
    chapter_title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding F32_BLOB(2560),         -- 阿里百炼 2560 维向量
    FOREIGN KEY(book_id) REFERENCES library_books(id) ON DELETE CASCADE
);

-- 3. 研习题库表
CREATE TABLE IF NOT EXISTS library_quizzes (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES library_books(id),
    chapter_title TEXT,
    question_type TEXT,               -- single (单选), multiple (多选), case (情境题)
    question TEXT NOT NULL,
    options TEXT NOT NULL,            -- JSON Array: ["A. xxx", "B. xxx", "C. xxx", "D. xxx"]
    correct_answer TEXT NOT NULL,     -- "A" 或 "A,C"
    explanation TEXT NOT NULL,        -- 题目解析与原书章节溯源
    difficulty INTEGER DEFAULT 1      -- 难度等级 1~5
);

-- 4. 概念记忆闪卡表 (Anki / 艾宾浩斯)
CREATE TABLE IF NOT EXISTS library_flashcards (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES library_books(id),
    front_prompt TEXT NOT NULL,       -- 卡片正面 (概念提问)
    back_answer TEXT NOT NULL,        -- 卡片背面 (原著金句与核心定理)
    tags TEXT                         -- 标签 (如: #逆向投资 #系统架构)
);
```

---

## 4. 详细实施路线规划 (四阶段渐进式落地)

### 📌 阶段一：电子书核心解析与全景重构引擎 (Core Pipeline)
- [ ] 编写电子书格式解析器：支持 `PDF`、`EPUB`、`MOBI`、`TXT`，提取高保真目录与纯净正文；
- [ ] 接入 TokenGate Gemini 100万长上下文通读模块：
  - 自动生成《3分钟极简透视与全书知识树》；
  - 自动生成《20%~25% 精华干货缩减本》；
- [ ] 接入 DeepSeek-V4-Pro 命题模块：
  - 自动生成 10~20 道精选章节测试题（带章节出处与错项排查）；
  - 自动提炼 15 张核心概念 Q&A 记忆闪卡；
  - 自动编写双人对谈播客剧本。

### 📌 阶段二：Turso 统一向量入库与 Rerank 跨书检索 (Vector RAG)
- [ ] 在 Turso 中创建 `library_*` 系列数据表；
- [ ] 接入 TokenGate `qwen3-vl-embedding` 完成 2560 维高精向量编码与入库；
- [ ] 封装跨书语义检索器：实现 `Embedding 向量初筛 ➔ Rerank 语义重排 ➔ DeepSeek 推理解答` 黄金检索链路。

### 📌 阶段三：双人对谈语音合成 (TTS) 与 Telegram Bot 随身交互做题
- [ ] 接入多角色自然语音合成（Edge-TTS / 阿里语音），输出男女双人对谈听书音频；
- [ ] 升级 Telegram Bot：
  - `/books`：查看第二大脑图书馆书单与精读状态；
  - `/study 《书名》`：获取该书 3分钟透视与缩减本；
  - `/quiz 《书名》`：启动交互式做题模式（TG 内联按键做题、即时判分、推报错题解析）；
  - `/listen 《书名》`：直接推送双人对谈听书音频到手机。

### 📌 阶段四：Quartz 5 数字花园发布与 Google Drive 自动监听
- [ ] 自动在 Quartz 内容库生成《精读书房》专栏笔记，内嵌 HTML5 音频播放器与折叠答题卡；
- [ ] 配置 N100 后台定时监听 Google Drive 电子书同步目录，实现“丢入电子书 ➔ 自动全套精读与题库生成”。

---

## 5. 验证与验收标准

1. **缩减本质量验证**：篇幅精确控制在原著 20%~25%，无注水废话，保留原书核心模型与脉络；
2. **测试题可用性验证**：在 Telegram Bot 中点击选择题按钮，秒级响应对错判定与解析；
3. **音频播放验证**：生成的双人对谈音频发到 Telegram 和 Quartz，音质清晰、语调自然、节奏生动；
4. **全域向量搜索验证**：在 TG 中提问跨书概念，准确召回相关书籍段落并由 DeepSeek 汇总。
