#!/bin/bash
# ==============================================================================
# 🚀 SecondBrain 全网四端多主题秒级自动化级联同步脚本 (N100 守护中心)
# 涵盖: Obsidian 知识库 -> Quartz + Nextra + MkDocs -> GitHub -> Cloudflare Pages
# ==============================================================================

export HTTPS_PROXY="http://192.168.2.3:7890"
export HTTP_PROXY="http://192.168.2.3:7890"
export NO_PROXY="localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com"

# 1. 同步 obsidian-brain-data 笔记到 Quartz content
if [ -d "/opt/obsidian-brain-data" ] && [ -d "/opt/SecondBrain-Quartz/content/notes" ]; then
    rsync -a --delete --exclude=".git" --exclude=".obsidian" /opt/obsidian-brain-data/ /opt/SecondBrain-Quartz/content/notes/
fi

# 2. 同步 obsidian-brain-data 笔记到 MkDocs docs
if [ -d "/opt/obsidian-brain-data" ] && [ -d "/opt/brain-theme-mkdocs/docs" ]; then
    rsync -a --exclude=".git" --exclude=".obsidian" --exclude="*.json" --exclude="*.txt" /opt/obsidian-brain-data/ /opt/brain-theme-mkdocs/docs/
fi

# 3. 监控并自动同步 obsidian-brain-data 知识库
cd /opt/obsidian-brain-data 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "$(date) - Changes detected in obsidian-brain-data. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add -A >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: auto sync notes from N100" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi

# 4. 监控并自动同步 SecondBrain-Quartz 仓库 (触发 Cloudflare Pages 自动构建)
cd /opt/SecondBrain-Quartz 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "$(date) - Changes detected in Quartz. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add -A >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: TG Bot & RSS content update" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi

# 5. 监控并自动同步 brain-theme-mkdocs 仓库 (触发 Cloudflare Pages MkDocs 自动构建)
cd /opt/brain-theme-mkdocs 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "$(date) - Changes detected in MkDocs. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add -A >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: publish latest Obsidian notes to MkDocs" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi

# 6. 同步 Nextra MDX 路由并推送 nas-gatekeeper (触发 Cloudflare Pages Nextra 自动构建)
cd /opt/nas-gatekeeper 2>/dev/null
if [ -f "/opt/nas-gatekeeper/apps/rss-fetcher/sync_nextra.py" ]; then
    /opt/SecondBrain-Flow/.venv/bin/python /opt/nas-gatekeeper/apps/rss-fetcher/sync_nextra.py >> /var/log/secondbrain_sync.log 2>&1
    if [[ -n $(git status -s frontends/nextra/pages/inbox frontends/nextra/pages/auto-clippings frontends/nextra/pages/auto-summary) ]]; then
        echo "$(date) - Nextra pages updated. Pushing to GitHub..." >> /var/log/secondbrain_sync.log
        git add frontends/nextra/pages/ >> /var/log/secondbrain_sync.log 2>&1
        git commit -m "Auto sync: publish latest Obsidian notes to Nextra" >> /var/log/secondbrain_sync.log 2>&1
        git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
        git push origin main >> /var/log/secondbrain_sync.log 2>&1
    fi
fi
