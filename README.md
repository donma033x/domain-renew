# DigitalPlat 免费域名自动续期脚本

自动续期 DigitalPlat (dash.domain.digitalplat.org) 的免费域名。

## 功能

- 支持多账号
- 自动登录
- 自动处理 Cloudflare 验证
- 自动续期即将到期的域名
- 保存会话供下次使用
- Telegram 通知

## 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖
uv sync

# 安装 Playwright 浏览器
uv run playwright install chromium
```

## 配置

```bash
cp .env.example .env
vim .env
```

```env
# 账号配置 (格式: email:password，多账号逗号分隔)
ACCOUNTS=email@example.com:password

# Telegram 通知 (可选)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 运行

```bash
xvfb-run uv run python do_renew.py
```

## 定时任务

```bash
crontab -e

# 每周日凌晨 3 点运行
0 3 * * 0 cd /path/to/domain-renew && xvfb-run /home/user/.local/bin/uv run python do_renew.py >> /tmp/domain-renew.log 2>&1
```
