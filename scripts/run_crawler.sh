#!/bin/bash
# N100 第二大脑全自动抓取与构建流水线 (含超时熔断与自愈机制)

LOCKFILE="/var/lock/secondbrain_crawler.lock"

# 检查是否存在超过 2 小时的僵死旧进程锁，若存在则自动清理自愈
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null)
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        # 检查进程启动时间
        ELAPSED_SEC=$(ps -p "$LOCK_PID" -o etimes= 2>/dev/null | tr -d ' ')
        if [ -n "$ELAPSED_SEC" ] && [ "$ELAPSED_SEC" -gt 7200 ]; then
            echo "⚠️ 检测到旧爬虫进程 (PID: $LOCK_PID) 运行已超过 2 小时 ($ELAPSED_SEC 秒)，自动熔断终止并释放锁 ($(date))" >> /var/log/secondbrain.log
            kill -9 "$LOCK_PID" 2>/dev/null || true
            rm -f "$LOCKFILE"
        fi
    fi
fi

# 进程锁：防止并发冲突
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "⚠️ 另一个爬虫流水线正在运行中，跳过本次执行 ($(date))" >> /var/log/secondbrain.log
    exit 0
fi
echo "$$" > "$LOCKFILE"

export HTTPS_PROXY="http://192.168.2.3:7890"
export HTTP_PROXY="http://192.168.2.3:7890"
export https_proxy="http://192.168.2.3:7890"
export http_proxy="http://192.168.2.3:7890"
export ALL_PROXY="http://192.168.2.3:7890"
export all_proxy="http://192.168.2.3:7890"
export NO_PROXY="localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com"
export no_proxy="localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com"

echo "=== Starting Crawl === $(date)" >> /var/log/secondbrain.log

# 1. 单向从 OneDrive 同步用户手写笔记 (带 30s 严格超时)
echo "⬇️ Syncing notes from OneDrive to N100..." >> /var/log/secondbrain.log
timeout 2m rclone sync onedrive:应用/remotely-save/notes/ /opt/obsidian-brain-data/ \
  --timeout 30s \
  --contimeout 10s \
  --retries 2 \
  --filter "- .obsidian/**" \
  --filter "- .git/**" \
  --filter "- .trash/**" \
  --filter "- .gitkeep" \
  --filter "- Auto_Clippings/**" \
  --filter "- Auto_Summary/**" \
  --filter "- Inbox/**" \
  --filter "- *.db*" \
  --filter "- .processed_items.db*" \
  -v >> /var/log/secondbrain.log 2>&1 || true

cd /opt/nas-gatekeeper/apps/rss-fetcher
export VAULT_PATH="/opt/obsidian-brain-data/Auto_Clippings"

# 2. 抓取 RSS 订阅源并深度提炼 (带 20 分钟硬超时熔断)
echo "🤖 Fetching RSS feeds (YouTube / Substack / Reddit / GitHub)..." >> /var/log/secondbrain.log
timeout 20m /opt/SecondBrain-Flow/.venv/bin/python -u rss_fetcher.py >> /var/log/secondbrain.log 2>&1 || true

# 3. 聚合当日所有简报生成综合日报 (带 5 分钟硬超时熔断)
echo "📊 Generating Daily Intelligence Digest..." >> /var/log/secondbrain.log
timeout 5m /opt/SecondBrain-Flow/.venv/bin/python -u daily_summary.py >> /var/log/secondbrain.log 2>&1 || true

# 4. 批量归档剪报与日报至 Google Drive
echo "☁️ Archiving Auto_Clippings & Auto_Summary to Google Drive..." >> /var/log/secondbrain.log
timeout 2m rclone copy /opt/obsidian-brain-data/Auto_Clippings/ gdrive:Auto_Clippings/ --timeout 30s --contimeout 10s --retries 2 >> /var/log/secondbrain.log 2>&1 || true
timeout 2m rclone copy /opt/obsidian-brain-data/Auto_Summary/ gdrive:Auto_Summary/ --timeout 30s --contimeout 10s --retries 2 >> /var/log/secondbrain.log 2>&1 || true

# 5. 同步至 Nextra 部署引擎
echo "🌐 Syncing notes to Nextra and pushing to Cloudflare..." >> /var/log/secondbrain.log
timeout 5m /opt/SecondBrain-Flow/.venv/bin/python -u sync_nextra.py >> /var/log/secondbrain.log 2>&1 || true

# 6. 同步至 Quartz 静态发布引擎
echo "🔮 Syncing notes to Quartz..." >> /var/log/secondbrain.log
rsync -a --delete --exclude=".git" --exclude=".obsidian" /opt/obsidian-brain-data/ /opt/SecondBrain-Quartz/content/notes/ >> /var/log/secondbrain.log 2>&1 || true

# 7. 推送到 GitHub 自动触发 Cloudflare Pages 构建
cd /opt/obsidian-brain-data
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "🐙 Pushing to Github..." >> /var/log/secondbrain.log
    git add . >> /var/log/secondbrain.log 2>&1
    git commit -m "Auto update: Sync from OneDrive, RSS clippings and Daily Summary" >> /var/log/secondbrain.log 2>&1
    timeout 2m git pull --rebase origin main >> /var/log/secondbrain.log 2>&1 || true
    timeout 2m git push origin main >> /var/log/secondbrain.log 2>&1 || true
fi

# 8. 向 TokenGate / Gatekeeper 探针大屏打卡发送心跳
echo "💓 Reporting heartbeat to Gatekeeper Probe Dashboard..." >> /var/log/secondbrain.log
ITEM_COUNT=$(sqlite3 /opt/nas-gatekeeper/apps/rss-fetcher/processed_items.db "SELECT count(*) FROM processed_items" 2>/dev/null || echo "0")
DAILY_NAME=$(ls -t /opt/obsidian-brain-data/Auto_Summary/*.md 2>/dev/null | head -n 1 | xargs -n 1 basename 2>/dev/null || echo "暂无")
curl -s -m 5 -X POST https://tg.donglida.com/api/heartbeat/crawler \
  -H "Content-Type: application/json" \
  -d "{\"status\": \"ok\", \"articles_today\": $ITEM_COUNT, \"daily_summary\": \"$DAILY_NAME\"}" >> /var/log/secondbrain.log 2>&1 || true

echo "=== Finished Crawl === $(date)" >> /var/log/secondbrain.log
