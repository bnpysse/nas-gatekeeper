#!/bin/bash
export HTTPS_PROXY="http://192.168.2.3:7890"
export HTTP_PROXY="http://192.168.2.3:7890"
export NO_PROXY="localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com"

echo "=== Starting Crawl === $(date)" >> /var/log/secondbrain.log

echo "⬇️ Syncing personal notes from OneDrive to N100..." >> /var/log/secondbrain.log
rclone sync onedrive:应用/remotely-save/notes/ /opt/obsidian-brain-data/ \
  --filter "- Auto_Clippings/**" \
  --filter "- Inbox/**" \
  --filter "- Pictures/**" \
  --filter "- TG_Clippings/**" \
  --filter "- Auto_Summary/**" \
  --filter "- .obsidian/**" \
  --filter "- .git/**" \
  --filter "- .gitkeep" \
  -v >> /var/log/secondbrain.log 2>&1

cd /opt/nas-gatekeeper/apps/rss-fetcher
export VAULT_PATH="/opt/obsidian-brain-data/Auto_Clippings"

echo "🤖 Fetching RSS feeds (YouTube / Substack / Reddit / GitHub)..." >> /var/log/secondbrain.log
/opt/SecondBrain-Flow/.venv/bin/python rss_fetcher.py >> /var/log/secondbrain.log 2>&1

echo "📊 Generating Daily Intelligence Digest..." >> /var/log/secondbrain.log
/opt/SecondBrain-Flow/.venv/bin/python daily_summary.py >> /var/log/secondbrain.log 2>&1

echo "🌐 Syncing notes to Nextra and pushing to Cloudflare..." >> /var/log/secondbrain.log
/opt/SecondBrain-Flow/.venv/bin/python sync_nextra.py >> /var/log/secondbrain.log 2>&1

echo "🔮 Syncing notes to Quartz..." >> /var/log/secondbrain.log
rsync -a --delete --exclude=".git" --exclude=".obsidian" /opt/obsidian-brain-data/ /opt/SecondBrain-Quartz/content/notes/ >> /var/log/secondbrain.log 2>&1

cd /opt/obsidian-brain-data
echo "🐙 Pushing to Github..." >> /var/log/secondbrain.log
git add . >> /var/log/secondbrain.log 2>&1
git commit -m "Auto update: Sync from OneDrive, RSS clippings and Daily Summary" >> /var/log/secondbrain.log 2>&1
git pull --rebase origin main >> /var/log/secondbrain.log 2>&1
git push origin main >> /var/log/secondbrain.log 2>&1

echo "=== Finished Crawl === $(date)" >> /var/log/secondbrain.log
