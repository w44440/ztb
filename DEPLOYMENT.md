# ZTB 部署文档

本文档描述 Ubuntu Server 上的定时抓取部署方式。定时任务只执行一个入口：

```bash
/home/leeway/projects/ztb/.venv/bin/ztb fetch
```

`ztb fetch` 会在 JYGS 抓取前自动从 RustFS/S3 下载并校验登录态文件，不需要 `ExecStartPre`。

## 1. 路径约定

- 项目目录：`/home/leeway/projects/ztb`
- 数据根目录：`/data/ops-data/ztb`
- JYGS 登录态：`/data/ops-data/ztb/auth/jygs_storage_state.json`
- 最近运行状态：`/data/ops-data/ztb/last_run.json`
- systemd user 环境文件：`/home/leeway/.config/ztb/ztb.env`
- systemd user unit：
  - `/home/leeway/.config/systemd/user/ztb-fetch.service`
  - `/home/leeway/.config/systemd/user/ztb-fetch.timer`

## 2. 环境变量

创建环境文件：

```bash
mkdir -p /home/leeway/.config/ztb
chmod 700 /home/leeway/.config/ztb
nano /home/leeway/.config/ztb/ztb.env
chmod 600 /home/leeway/.config/ztb/ztb.env
```

示例内容：

```ini
ZTB_DATA_ROOT=/data/ops-data/ztb
ZTB_JYGS_HEADLESS=true

# Cloudflare R2 / RustFS / MinIO / S3-compatible object storage
ZTB_STATE_S3_ENDPOINT=<account_id>.r2.cloudflarestorage.com
ZTB_STATE_S3_ACCESS_KEY=your-access-key
ZTB_STATE_S3_SECRET_KEY=your-secret-key
ZTB_STATE_S3_BUCKET=ztb

# Optional: WeCom webhook. If unset, notification is skipped.
ZTB_WECHAT_WEBHOOK=
```

说明：

- `ZTB_STATE_S3_ENDPOINT` 不需要写 bucket。Cloudflare R2 使用 `<account_id>.r2.cloudflarestorage.com`。
- endpoint 可以带 `https://`，也可以不带；不带时默认按 HTTPS 处理。
- R2 region 固定使用 `auto`，无需配置。
- 对象名固定为 `jygs_state.json`，无需配置。
- `ZTB_WECHAT_WEBHOOK` 可留空，不影响抓取和入库。
- `ZTB_JYGS_AUTH_STATE_PATH` 通常不用配；默认随 `ZTB_DATA_ROOT` 走。

## 3. 首次部署

安装项目依赖：

```bash
cd /home/leeway/projects/ztb
uv sync --frozen
uv run playwright install chromium
```

安装 Chromium 系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
  libcairo2 libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 \
  libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 \
  libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 xvfb \
  fonts-noto-color-emoji fonts-unifont libfontconfig1 libfreetype6 \
  xfonts-cyrillic xfonts-scalable fonts-liberation fonts-ipafont-gothic \
  fonts-wqy-zenhei fonts-tlwg-loma-otf fonts-freefont-ttf
```

准备数据目录：

```bash
mkdir -p /data/ops-data/ztb
```

确认入口可执行：

```bash
cd /home/leeway/projects/ztb
.venv/bin/ztb --help
```

## 4. 生成并上传 JYGS 登录态

这一步在有图形界面的本地 Linux/WSL 环境执行，不在无桌面的 Ubuntu Server 上做人工登录。

本地环境也需要项目代码、依赖和同一份 RustFS 环境变量。建议用临时数据目录生成登录态：

```bash
cd /home/leeway/projects/ztb
uv sync --frozen
uv run playwright install chromium

export ZTB_DATA_ROOT=/tmp/ztb-login-data
export ZTB_STATE_S3_ENDPOINT=<account_id>.r2.cloudflarestorage.com
export ZTB_STATE_S3_ACCESS_KEY=your-access-key
export ZTB_STATE_S3_SECRET_KEY=your-secret-key
export ZTB_STATE_S3_BUCKET=ztb
```

打开浏览器登录并生成 state：

```bash
uv run ztb login
```

上传到 RustFS：

```bash
uv run ztb auth upload-jygs-state
```

服务器端验证下载和校验：

```bash
cd /home/leeway/projects/ztb
set -a
. /home/leeway/.config/ztb/ztb.env
set +a
uv run ztb auth download-jygs-state
uv run ztb auth check-jygs-state
```

## 5. systemd user 定时任务

开启 linger，确保用户未登录时 user systemd 也会运行：

```bash
sudo loginctl enable-linger leeway
loginctl show-user leeway -p Linger
```

创建 service：

```bash
mkdir -p /home/leeway/.config/systemd/user
nano /home/leeway/.config/systemd/user/ztb-fetch.service
```

内容：

```ini
[Unit]
Description=ZTB daily fetch
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/leeway/projects/ztb
Environment=HOME=/home/leeway
EnvironmentFile=/home/leeway/.config/ztb/ztb.env
ExecStart=/home/leeway/projects/ztb/.venv/bin/ztb fetch
TimeoutStartSec=30min
StandardOutput=journal
StandardError=journal
```

创建 timer：

```bash
nano /home/leeway/.config/systemd/user/ztb-fetch.timer
```

内容：

```ini
[Unit]
Description=Run ZTB fetch at 16:00 on weekdays

[Timer]
OnCalendar=Mon..Fri 16:00:00
Persistent=true
AccuracySec=1min
RandomizedDelaySec=0
Unit=ztb-fetch.service

[Install]
WantedBy=timers.target
```

启用：

```bash
systemctl --user daemon-reload
systemctl --user enable --now ztb-fetch.timer
systemctl --user list-timers ztb-fetch.timer
```

## 6. 验证

手动运行一次 service：

```bash
systemctl --user start ztb-fetch.service
```

查看日志：

```bash
journalctl --user -u ztb-fetch.service -n 120 --no-pager
```

查看抓取状态：

```bash
cat /data/ops-data/ztb/last_run.json
```

检查 timer：

```bash
systemctl --user status ztb-fetch.timer --no-pager
systemctl --user list-timers --all | rg ztb-fetch
```

## 7. 日常维护

代码更新后：

```bash
cd /home/leeway/projects/ztb
uv sync --frozen
systemctl --user restart ztb-fetch.timer
```

只改 Python 代码且依赖未变时，通常不需要 `uv sync --frozen`；下一次 systemd 执行会加载当前工作区代码。

JYGS 登录态过期时：

```bash
# 在有图形界面的本地 Linux/WSL 环境
cd /home/leeway/projects/ztb
export ZTB_DATA_ROOT=/tmp/ztb-login-data
# 同步设置 ZTB_STATE_S3_* 环境变量
uv run ztb login
uv run ztb auth upload-jygs-state

# 在服务器验证
cd /home/leeway/projects/ztb
set -a
. /home/leeway/.config/ztb/ztb.env
set +a
uv run ztb auth download-jygs-state
uv run ztb auth check-jygs-state
```

## 8. 排障

缺 Chromium 系统库：

```bash
uv run playwright install-deps --dry-run chromium
```

按输出安装缺失 apt 包。

对象存储配置缺失：

```bash
uv run ztb auth download-jygs-state
```

如果提示 `缺少环境变量: ZTB_STATE_S3_*`，检查 `/home/leeway/.config/ztb/ztb.env` 是否被 systemd service 加载。

登录态无效：

```bash
uv run ztb auth check-jygs-state
```

如果提示状态文件过期，重新在本地生成并上传。

网络或 RustFS 不可达：

```bash
curl -I http://127.0.0.1:9000
journalctl --user -u ztb-fetch.service -n 120 --no-pager
```
