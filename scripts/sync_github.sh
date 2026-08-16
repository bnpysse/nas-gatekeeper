#!/bin/bash
export HTTPS_PROXY="http://192.168.2.3:7890"
export HTTP_PROXY="http://192.168.2.3:7890"
export NO_PROXY="localhost,127.0.0.1,dashscope.aliyuncs.com,ark.cn-beijing.volces.com"

# 1. 监控并自动同步 obsidian-brain-data 知识库
cd /opt/obsidian-brain-data 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s) ]]; then
    echo "$(date) - Changes detected in obsidian-brain-data. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add -A >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: auto sync notes from N100" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi

# 2. 监控并自动同步 SecondBrain-Quartz 仓库
cd /opt/SecondBrain-Quartz 2>/dev/null
if [[ -d .git ]] && [[ -n $(git status -s content/notes) ]]; then
    echo "$(date) - Changes detected in Quartz notes. Syncing with GitHub..." >> /var/log/secondbrain_sync.log
    git add content/notes >> /var/log/secondbrain_sync.log 2>&1
    git commit -m "Auto sync: TG Bot & RSS content update" >> /var/log/secondbrain_sync.log 2>&1
    git pull --rebase origin main >> /var/log/secondbrain_sync.log 2>&1
    git push origin main >> /var/log/secondbrain_sync.log 2>&1
fi
