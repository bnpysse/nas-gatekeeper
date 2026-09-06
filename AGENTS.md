# Workspace Rules & User Preferences

## Shell & Environment
- **Shell**: The user uses **Fish Shell** (`fish`) on both the local Mac and the N100 server.
- When providing shell commands, scripts, or instructions in responses:
  - Provide syntax compatible with Fish Shell.
  - For Python virtual environments, use `source <venv>/bin/activate.fish`.
  - For setting environment variables, use `set -gx KEY value` or `set -x KEY value` instead of `export KEY=value` (or explain both if needed).
  - In Fish shell, beware of bashisms like heredocs (`cat << 'EOF'`), `&&`, or unquoted wildcard globs (`ls *token*` fails if no match). Wrap multiline scripts in `bash -c '...'` if needed.

## Infrastructure & Host Architecture
- **N100 Physical Server (PVE Virtualization)**:
  - **PVE Node (Host)**: Accessible via Web Console (`https://<PVE-IP>:8006`), Shell prompt `root@pve:~#`.
  - **LXC Container 100 (`PrismML`)**:
    - SSH Access: `ssh n100` or `ssh root@donglida.xyz -p 30022`.
    - **PVE vs LXC Distinction**: `ssh n100` logs into LXC Container 100 (`PrismML`), **NOT** the PVE host. Do not look for `/dev/pve` block devices inside the container. PVE host-level ops (disk resizing, hardware pool checks) must be guided to the PVE Web Console node shell (`root@pve:~#`).
    - LAN IP: `192.168.2.9` (Gateway: `192.168.2.1`, Bypass Proxy: `192.168.2.3:7890`).
    - Tailscale IP: `100.114.85.62`.
    - Storage: LXC rootfs on `/dev/pve/vm-100-disk-0` resized cleanly to **384GB** (usable ~377GB, used ~42GB).
    - Container Engine: **Podman 5.4.2** (daemonless, compatible with docker commands). Managed systemd units follow `container-<name>.service` pattern.
  - **Aliyun VPS Relay Node**:
    - IP: `47.101.190.145` (SSH: `root@47.101.190.145`).
    - Hosts TokenGate API (`:8800`), Omni App (`:8501`), Robyn backend (`:8080`).

## Important Operations & Guardrails
- **Crawler & SecondBrain Protection**: Mature crawling & self-healing system is in production. Do **not** arbitrarily delete or refactor `/opt/run_crawler.sh` or `/opt/SecondBrain-Flow`.
- **Fish Shell Precautions**: Avoid `cat << 'EOF'`, bare `&&`, or unquoted wildcards (`ls *.db*` fails if unmatched). Enclose complex multiline scripts in `bash -c "..."` or write to a temporary script file.
- **Cloudflare Ingress Changes**: Changes to reverse proxies or container ports must be verified against `/etc/cloudflared/config.yml`.

## Key Services on N100 (`PrismML`)
1. **AList (Official Docker / Podman Container)**:
   - Container Name: `alist`, Managed by systemd unit: `container-alist.service`.
   - Port: `5244`.
   - Data & Config: `/opt/alist/data` (mapped to `/opt/alist/data`).
   - Host Storage Mount: `/opt` on N100 is mapped inside container as `/opt/host_opt:ro`.
   - Web Access:
     - Cloudflare Tunnel: `https://alist.donglida.com` (and `https://alist.imdld.com` in ingress).
     - LAN: `http://192.168.2.9:5244`.
     - Admin: `admin` / `Admin123456`.
2. **Obsidian Telegram Bot**:
   - Systemd Service: `obsidian_bot.service`.
   - Path: `/opt/SecondBrain-Flow/.venv/bin/python /opt/nas-gatekeeper/apps/tg-bot/bot.py`.
   - Mode: Polling `api.telegram.org` directly.
3. **RSS Pipeline & SecondBrain Daily Summary**:
   - Triggered via crontab: `0 */2 * * * bash /opt/run_crawler.sh >> /var/log/secondbrain_cron.log 2>&1`.
   - Script: `/opt/run_crawler.sh` (pulls RSS, calls DeepSeek-V4 for daily summary, syncs to Google Drive, pushes to Cloudflare/Quartz).
4. **Autonomous Doctor Agent (`crawler_doctor.py`)**:
   - Triggered via crontab: `*/30 * * * * ... crawler_doctor.py --check >> /var/log/crawler_doctor.log 2>&1`.
5. **TokenGate Client / Probe**:
   - CLI executable: `/usr/local/bin/tokengate` (queries `https://tg.donglida.com/api/quotas`).
   - Central probe backend is hosted on Aliyun VPS (`47.101.190.145:8800`) behind Cloudflare (`tg.donglida.com`).
6. **Cloudflare Tunnel (`cloudflared.service`)**:
   - Config: `/etc/cloudflared/config.yml`.
   - Ingresses: `lib.donglida.com`, `library.imdld.com` (:8888), `brain.imdld.com` (:80), `alist.donglida.com` (:5244), `alist.imdld.com` (:5244).

