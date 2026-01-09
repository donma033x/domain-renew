# DigitalPlat 免费域名自动续期脚本

自动续期 DigitalPlat (dash.domain.digitalplat.org) 的免费域名。

## 功能

- 支持多账号
- 自动登录
- 自动处理 Cloudflare 验证
- 自动续期即将到期的域名
- 保存会话供下次使用
- Telegram 通知

## 安装 (uv)

```bash
# 安装 uv (如果没有)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖
uv sync

# 安装 Playwright 浏览器
uv run playwright install chromium
```

## 配置

```bash
# 复制配置文件
cp .env.example .env

# 编辑配置
vim .env
```

配置项说明:

```env
# 账号配置 (格式: email:password)
# 多个账号用逗号分隔
ACCOUNTS=email1@example.com:password1,email2@example.com:password2

# Telegram 通知 (可选)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 运行

```bash
# 使用 xvfb (推荐，更稳定)
xvfb-run uv run python do_renew.py

# 或直接运行 (需要桌面环境)
uv run python do_renew.py
```

## 定时任务

使用 cron 定期执行:

```bash
crontab -e

# 每周日凌晨 3 点运行
0 3 * * 0 cd /path/to/domain-renew && xvfb-run uv run python do_renew.py >> /tmp/domain-renew.log 2>&1
```

## 目录结构

```
domain-renew/
├── do_renew.py       # 主脚本
├── pyproject.toml    # 项目配置
├── .env              # 配置文件
├── .env.example      # 配置模板
├── sessions/         # 会话存储
└── README.md
```

## 注意事项

1. 免费域名通常有效期为 1 年，需要在到期前续期
2. 建议每周或每月执行一次
3. `headless=False` 需要显示环境，所以要用 `xvfb-run`
