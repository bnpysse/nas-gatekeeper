#!/bin/bash
export HTTPS_PROXY="http://192.168.2.3:7890"
export HTTP_PROXY="http://192.168.2.3:7890"
export NO_PROXY="localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com"

# 1. 自动同步 obsidian-brain-data 笔记到 Quartz content
if [ -d "/opt/obsidian-brain-data" ] && [ -d "/opt/SecondBrain-Quartz/content/notes" ]; then
    rsync -a --delete --exclude=".git" --exclude=".obsidian" /opt/obsidian-brain-data/ /opt/SecondBrain-Quartz/content/notes/
fi

# 2. 监控并自动同步 obsidian-brain-data 知识库
cd /opt/obsidian-brain-data 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "$(date) - Changes detected in obsidian-brain-data. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add -A >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: auto sync notes from N100" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi

# 3. 监控并自动同步 SecondBrain-Quartz 仓库 (触发 Cloudflare Pages 自动构建)
cd /opt/SecondBrain-Quartz 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "$(date) - Changes detected in Quartz. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add -A >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: TG Bot & RSS content update" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi

# 4. 同步 Nextra MDX 路由并推送 nas-gatekeeper (触发 Cloudflare Pages Nextra 自动构建)
cd /opt/nas-gatekeeper 2>/dev/null
if [ -f "/opt/nas-gatekeeper/apps/rss-fetcher/sync_nextra.py" ]; then
    /opt/SecondBrain-Flow/.venv/bin/python /opt/nas-gatekeeper/apps/rss-fetcher/sync_nextra.py >> /var/log/secondbrain_sync.log 2>&1
    if [[ -n $(git status -s frontends/nextra/pages/auto-clippings) ]]; then
        echo "$(date) - Nextra pages updated. Pushing to GitHub..." >> /var/log/secondbrain_sync.log
        git add frontends/nextra/pages/auto-clippings >> /var/log/secondbrain_sync.log 2>&1
        git commit -m "Auto sync: publish latest notes to Nextra" >> /var/log/secondbrain_sync.log 2>&1
        git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
        git push origin main >> /var/log/secondbrain_sync.log 2>&1
    fi
fi
