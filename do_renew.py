#!/usr/bin/env python3
"""
域名续期执行脚本 - 自动发现并续期所有域名 + Telegram 通知
"""

import asyncio
import json
import re
import requests
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

# ==================== 加载配置 ====================
def load_env():
    env_file = Path(__file__).parent / '.env'
    env_vars = {}
    if not env_file.exists():
        return env_vars
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars

ENV = load_env()

# 账号配置
ACCOUNTS_STR = ENV.get('ACCOUNTS', '')

# Telegram 配置
TELEGRAM_BOT_TOKEN = ENV.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = ENV.get('TELEGRAM_CHAT_ID', '')

SESSION_DIR = Path(__file__).parent / "sessions"
LOG_FILE = Path(__file__).parent / f"renew_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

def parse_accounts(accounts_str: str) -> list:
    accounts = []
    if not accounts_str:
        return accounts
    for item in accounts_str.split(','):
        item = item.strip()
        if ':' in item:
            email, password = item.split(':', 1)
            accounts.append({'email': email.strip(), 'password': password.strip()})
    return accounts

def get_session_file(email: str) -> Path:
    SESSION_DIR.mkdir(exist_ok=True)
    safe_name = email.replace('@', '_at_').replace('.', '_')
    return SESSION_DIR / f"{safe_name}.json"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        log(f"Telegram 发送失败: {e}")
        return False

async def cdp_click(cdp, x, y):
    await cdp.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})
    await asyncio.sleep(0.1)
    await cdp.send('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
    await asyncio.sleep(0.05)
    await cdp.send('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

async def handle_cloudflare(page, cdp, max_attempts=30):
    for attempt in range(max_attempts):
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=5000)
            title = await page.title()
            if "Just a moment" not in title:
                return True
        except:
            pass
        try:
            wrapper = await page.query_selector('.main-wrapper')
            if wrapper:
                rect = await wrapper.bounding_box()
                if rect:
                    x, y = int(rect['x'] + 25), int(rect['y'] + rect['height'] / 2)
                    await cdp_click(cdp, x, y)
        except:
            pass
        await asyncio.sleep(2)
    return False

async def handle_security(page, cdp):
    content = await page.content()
    if 'Security Check' in content:
        log("处理 Security Check...")
        await cdp_click(cdp, 520, 550)
        await asyncio.sleep(5)
        for i in range(10):
            content = await page.content()
            if 'Security Check' not in content:
                log("Security Check 通过!")
                return True
            await asyncio.sleep(1)
    return True

async def handle_turnstile(page, cdp):
    await cdp_click(cdp, 477, 391)
    await asyncio.sleep(3)

def parse_expire_date(text: str) -> str:
    match = re.search(r'Expire Date:\s*(\d{8})', text)
    if match:
        date_str = match.group(1)
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return "未知"

def days_until_expire(expire_date: str) -> int:
    """计算距离到期还有多少天"""
    if expire_date == "未知":
        return -1
    try:
        expire = datetime.strptime(expire_date, "%Y-%m-%d")
        delta = expire - datetime.now()
        return delta.days
    except:
        return -1

async def login(page, cdp, context, email, password):
    """Login if needed"""
    log(f"登录 {email}...")
    
    await page.goto("https://dash.domain.digitalplat.org/auth/login")
    await asyncio.sleep(3)
    
    if not await handle_cloudflare(page, cdp):
        return False
    
    await asyncio.sleep(2)
    
    # Accept cookies
    try:
        accept = await page.query_selector('button:has-text("Accept all")')
        if accept:
            await accept.click()
            await asyncio.sleep(1)
    except:
        pass
    
    # Step 1: Email
    email_input = await page.query_selector('input[placeholder="you@example.com"]')
    if email_input:
        await email_input.fill(email)
        log(f"邮箱: {email}")
    
    next_btn = await page.query_selector('button:has-text("Next")')
    if next_btn:
        await next_btn.click()
    await asyncio.sleep(3)
    
    # Step 2: Password
    pwd_input = await page.query_selector('input[placeholder="Your password"]')
    if pwd_input:
        await pwd_input.fill(password)
        log("密码已输入")
    
    await asyncio.sleep(2)
    
    # Turnstile
    await handle_turnstile(page, cdp)
    await asyncio.sleep(3)
    
    # Login button
    login_btn = await page.query_selector('button:has-text("Login")')
    if login_btn:
        await login_btn.click()
    
    await asyncio.sleep(5)
    await handle_cloudflare(page, cdp, 10)
    await asyncio.sleep(2)
    
    url = page.url
    if 'login' not in url.lower():
        log("登录成功!")
        return True
    
    log("登录失败")
    return False

async def get_domains(page, cdp):
    """Get list of domains with retry"""
    log("获取域名列表...")
    
    for retry in range(3):
        await page.goto("https://dash.domain.digitalplat.org/")
        await asyncio.sleep(3)
        await handle_cloudflare(page, cdp, 15)
        await handle_security(page, cdp)
        await asyncio.sleep(2)
        
        # Click My Domains
        my_domains = await page.query_selector('a:has-text("My Domains")')
        if my_domains:
            await my_domains.click()
            await asyncio.sleep(3)
        
        await handle_security(page, cdp)
        await asyncio.sleep(2)
        
        # Get iframe content
        iframe = await page.query_selector('iframe')
        if not iframe:
            if retry < 2:
                log(f"未找到 iframe，重试 {retry + 1}/3...")
                continue
            return []
        
        frame = await iframe.content_frame()
        if not frame:
            if retry < 2:
                log(f"无法访问 iframe，重试 {retry + 1}/3...")
                continue
            return []
        
        # Extract domains
        content = await frame.evaluate('() => document.body.innerText')
        
        # Match domain patterns
        domain_pattern = re.compile(r'([\w-]+\.(us\.kg|pp\.ua|eu\.org|nom\.za|co\.za))')
        matches = domain_pattern.findall(content)
        domains = list(set([m[0] for m in matches]))
        
        if domains:
            break
        
        if retry < 2:
            log(f"未找到域名，重试 {retry + 1}/3...")
            await asyncio.sleep(2)
    
    log(f"找到 {len(domains)} 个域名: {domains}")
    return domains

async def renew_domain(page, cdp, domain):
    """Renew a single domain"""
    log(f"\n{'='*50}")
    log(f"处理域名: {domain}")
    log(f"{'='*50}")
    
    old_expire = ""
    new_expire = ""
    
    # Go to domain manager
    await page.goto(f"https://dash.domain.digitalplat.org/panel/main?page=%2Fpanel%2Fmanager%2F{domain}")
    await asyncio.sleep(3)
    await handle_cloudflare(page, cdp, 15)
    await handle_security(page, cdp)
    await asyncio.sleep(2)
    
    # Get iframe with retry
    domain_info = ""
    for retry in range(3):
        iframe = await page.query_selector('iframe')
        if not iframe:
            if retry < 2:
                log(f"未找到 iframe，重试 {retry + 1}/3...")
                await asyncio.sleep(3)
                continue
            raise Exception("未找到 iframe")
        
        frame = await iframe.content_frame()
        if not frame:
            if retry < 2:
                log(f"无法访问 iframe，重试 {retry + 1}/3...")
                await asyncio.sleep(3)
                continue
            raise Exception("无法访问 iframe")
        
        # Get domain info
        domain_info = await frame.evaluate('() => document.body.innerText')
        old_expire = parse_expire_date(domain_info)
        
        # 如果成功获取到期日期，跳出循环
        if old_expire != "未知":
            break
        
        # 内容未加载完成，等待后重试
        if retry < 2:
            log(f"iframe 内容未加载完成，重试 {retry + 1}/3...")
            await asyncio.sleep(3)
    
    log(f"当前到期日期: {old_expire}")
    
    # 检查是否在续期窗口内 (180天)
    days_left = days_until_expire(old_expire)
    if days_left > 180:
        log(f"{domain} 距到期还有 {days_left} 天，超过180天，暂不需要续期")
        return {'domain': domain, 'success': False, 'old_expire': old_expire, 'new_expire': old_expire, 'error': f'距到期{days_left}天，暂不需续期', 'skip': True}
    elif days_left > 0:
        log(f"{domain} 距到期还有 {days_left} 天，在续期窗口内")
    
    # Click Renew button
    renew_btn = await frame.query_selector('button:has-text("Renew")')
    if not renew_btn:
        raise Exception("未找到 Renew 按钮")
    
    log("点击 Renew 按钮...")
    await renew_btn.click()
    await asyncio.sleep(3)
    await handle_security(page, cdp)
    await asyncio.sleep(2)
    
    # Refresh frame
    iframe = await page.query_selector('iframe')
    frame = await iframe.content_frame() if iframe else None
    if not frame:
        raise Exception("重新获取 frame 失败")
    
    # Check for Free Renewal button
    free_renewal = await frame.query_selector('button:has-text("Free Renewal")')
    if not free_renewal:
        log(f"{domain} 未找到 Free Renewal 按钮，可能尚未到续期时间")
        return {'domain': domain, 'success': False, 'old_expire': old_expire, 'new_expire': old_expire, 'error': '未到续期时间', 'skip': False}
    
    # Click Free Renewal
    log("点击 Free Renewal...")
    await free_renewal.click()
    await asyncio.sleep(5)
    
    # Check for confirm dialog
    iframe = await page.query_selector('iframe')
    frame = await iframe.content_frame() if iframe else None
    if frame:
        confirm = await frame.query_selector('button:has-text("Confirm"), button:has-text("Yes"), button:has-text("OK")')
        if confirm:
            log("点击确认...")
            await confirm.click()
            await asyncio.sleep(3)
    
    await handle_security(page, cdp)
    await asyncio.sleep(3)
    
    # Get result
    iframe = await page.query_selector('iframe')
    frame = await iframe.content_frame() if iframe else None
    if frame:
        result = await frame.evaluate('() => document.body.innerText')
        new_expire = parse_expire_date(result)
    
    log(f"新到期日期: {new_expire}")
    
    success = new_expire != old_expire or new_expire != "未知"
    return {'domain': domain, 'success': success, 'old_expire': old_expire, 'new_expire': new_expire, 'error': None, 'skip': False}

async def process_account(email: str, password: str):
    """Process a single account"""
    log(f"\n{'#'*60}")
    log(f"处理账号: {email}")
    log(f"{'#'*60}")
    
    session_file = get_session_file(email)
    results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        cdp = await context.new_cdp_session(page)
        
        try:
            # Load session
            if session_file.exists():
                with open(session_file) as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                log("会话已加载")
            
            # Check login status
            await page.goto("https://dash.domain.digitalplat.org/")
            await asyncio.sleep(3)
            await handle_cloudflare(page, cdp)
            await handle_security(page, cdp)
            await asyncio.sleep(2)
            
            url = page.url
            if 'login' in url.lower():
                log("需要登录")
                if not await login(page, cdp, context, email, password):
                    return []
            else:
                log("已登录")
            
            # Get domains
            domains = await get_domains(page, cdp)
            
            if not domains:
                log("未找到域名")
                return []
            
            # Renew each domain
            for domain in domains:
                try:
                    result = await renew_domain(page, cdp, domain)
                    results.append(result)
                except Exception as e:
                    log(f"{domain} 续期失败: {e}")
                    results.append({'domain': domain, 'success': False, 'old_expire': '', 'new_expire': '', 'error': str(e), 'skip': False})
            
            # Save session
            cookies = await context.cookies()
            with open(session_file, 'w') as f:
                json.dump(cookies, f, indent=2)
            log("会话已保存")
            
        except Exception as e:
            log(f"账号处理失败: {e}")
        finally:
            await browser.close()
    
    return results

async def main():
    log("=" * 60)
    log("域名自动续期开始")
    log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)
    
    accounts = parse_accounts(ACCOUNTS_STR)
    if not accounts:
        log("错误: 未配置账号")
        return False
    
    log(f"账号数量: {len(accounts)}")
    
    all_results = []
    errors = []
    
    for account in accounts:
        try:
            results = await process_account(account['email'], account['password'])
            if results:
                all_results.extend(results)
            else:
                errors.append(f"{account['email']}: 未获取到域名或处理失败")
        except Exception as e:
            errors.append(f"{account['email']}: {str(e)}")
            log(f"账号 {account['email']} 处理异常: {e}")
    
    # Summary
    log("\n" + "=" * 60)
    log("任务汇总")
    log("=" * 60)
    
    success_count = sum(1 for r in all_results if r['success'])
    skip_count = sum(1 for r in all_results if r.get('skip', False))
    need_renew_count = len(all_results) - skip_count
    
    for r in all_results:
        if r.get('skip'):
            status = "⏭"
        elif r['success']:
            status = "✓"
        else:
            status = "✗"
        log(f"{status} {r['domain']}: {r['old_expire']} -> {r['new_expire']}")
    
    log(f"\n总计: {success_count} 成功, {skip_count} 跳过, {len(all_results)} 总数")
    
    # Send Telegram notification
    if all_results or errors:
        # 判断通知类型
        if errors and not all_results:
            # 全部失败
            emoji = "🚨"
            title = "域名续期失败 - 请检查"
        elif errors:
            # 部分失败
            emoji = "⚠️"
            title = "域名续期异常 - 部分账号失败"
        elif skip_count == len(all_results):
            # 全部跳过
            emoji = "💤"
            title = "域名检查完成 - 暂无需续期"
        elif success_count == need_renew_count and need_renew_count > 0:
            emoji = "✅"
            title = "域名续期成功"
        elif success_count > 0:
            emoji = "⚠️"
            title = "域名续期部分成功"
        else:
            emoji = "ℹ️"
            title = "域名续期完成"
        
        lines = [f"{emoji} <b>{title}</b>", ""]
        
        # 显示错误信息
        if errors:
            lines.append("<b>❌ 错误:</b>")
            for err in errors:
                lines.append(f"   {err}")
            lines.append("")
        
        # 显示域名结果
        if all_results:
            for r in all_results:
                if r.get('skip'):
                    status = "⏭️"
                elif r['success']:
                    status = "✅"
                else:
                    status = "❌"
                lines.append(f"{status} <code>{r['domain']}</code>")
                lines.append(f"   到期: {r['new_expire'] or r['old_expire']}")
                if r['error']:
                    lines.append(f"   备注: {r['error']}")
        
        lines.append("")
        lines.append(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        msg = "\n".join(lines)
        if send_telegram(msg):
            log("Telegram 通知已发送")
        else:
            log("Telegram 通知发送失败")
    else:
        # 没有任何结果也没有错误，发送异常通知
        msg = f"🚨 <b>域名续期异常</b>\n\n未获取到任何域名信息，脚本可能运行异常\n\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        send_telegram(msg)
        log("发送异常通知")
    
    return (success_count > 0 or skip_count > 0) and not errors

if __name__ == '__main__':
    result = asyncio.run(main())
    print(f"\n日志文件: {LOG_FILE}")
    exit(0 if result else 1)
