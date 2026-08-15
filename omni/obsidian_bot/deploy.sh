#!/usr/bin/env bash

# 一键部署脚本：部署 Woodman Brain Bot 到 Linux N100 小主机

set -e

echo "=== 开始部署 Woodman Brain Bot 到 N100 服务器 ==="

# 1. 基础依赖校验与安装
if ! command -v ffmpeg &> /dev/null; then
    echo "[!] 未检测到 ffmpeg，正在自动安装..."
    apt-get update && apt-get install -y ffmpeg
fi

if ! command -v yt-dlp &> /dev/null; then
    echo "[!] 未检测到 yt-dlp，正在通过 pip 安装..."
    pip3 install -U yt-dlp
fi

# 2. 创建部署路径
TARGET_DIR="/opt/obsidian_bot"
CONF_DIR="/etc/nas-gatekeeper"

mkdir -p "$TARGET_DIR"
mkdir -p "$CONF_DIR"

# 3. 复制代码文件
echo "[+] 复制代码到 $TARGET_DIR..."
cp -r ./* "$TARGET_DIR/"

# 4. 安装 Python 依赖
echo "[+] 安装 Python 依赖..."
pip3 install -r "$TARGET_DIR/requirements.txt"

# 5. 配置文件初始化
ENV_TARGET="$CONF_DIR/obsidian_bot.env"
if [ ! -f "$ENV_TARGET" ]; then
    echo "[+] 正在初始化配置文件 $ENV_TARGET..."
    cp "$TARGET_DIR/.env.template" "$ENV_TARGET"
    chmod 600 "$ENV_TARGET"
    echo "[!] 警告：请务必编辑 $ENV_TARGET 填入真实的 TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID 和 GEMINI_PKM_API_KEY！"
else
    chmod 600 "$ENV_TARGET"
    echo "[✓] 已存在配置文件 $ENV_TARGET，权限已更新为 600。"
fi

# 6. 安装 Systemd 服务
echo "[+] 配置 Systemd 守护进程..."
cp "$TARGET_DIR/systemd/obsidian-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable obsidian-bot.service

echo "=== [SUCCESS] 部署就绪！ ==="
echo "请确认 $ENV_TARGET 已配置完成后，运行以下命令启动服务："
echo "systemctl restart obsidian-bot.service"
echo "查看服务日志：journalctl -u obsidian-bot.service -f"
