"""浏览器 Cookie 自动提取工具 — 多重策略

策略优先级（按 Cookie 可用性排序）:
1. 剪贴板 — 用户从 F12 DevTools 复制，Cookie 保证可用于 API
2. rookiepy — 直接读 Chrome/Edge 加密 Cookie 数据库（需管理员）
3. CDP 交互式 — 弹出浏览器等待手动登录（Cookie 可能仅限浏览器内有效）
"""

import os
import sys
import subprocess
import time
import socket
import tempfile
from pathlib import Path
from typing import Optional

if __name__ != "__main__":
    from utils.logger import logger
else:
    import logging
    logger = logging.getLogger("cookie_util")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from config import REAL_LOGIN_KEYS, GUEST_KEYS


def _find_system_browser():
    """查找系统 Chrome/Edge 路径"""
    paths = []
    local = os.getenv("LOCALAPPDATA", "")
    roaming = os.getenv("APPDATA", "")

    candidates = [
        (Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe", "Edge"),
        (Path(roaming) / "Google" / "Chrome" / "Application" / "chrome.exe", "Chrome"),
        (Path("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"), "Chrome"),
        (Path("C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"), "Chrome"),
        (Path("C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"), "Edge"),
        (Path("C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"), "Edge"),
    ]
    for p, name in candidates:
        if p.exists():
            paths.append((str(p), name))
    return paths if paths else None


def _find_real_profiles():
    """查找用户真实的 Chrome/Edge Profile 目录（包含已登录 Cookie）"""
    local = os.getenv("LOCALAPPDATA", "")
    profiles = []

    chrome_data = Path(local) / "Google" / "Chrome" / "User Data"
    if chrome_data.exists():
        for d in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
            p = chrome_data / d
            if p.exists():
                profiles.append((str(p), "Chrome", str(chrome_data)))

    edge_data = Path(local) / "Microsoft" / "Edge" / "User Data"
    if edge_data.exists():
        for d in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
            p = edge_data / d
            if p.exists():
                profiles.append((str(p), "Edge", str(edge_data)))

    return profiles


def _is_browser_profile_in_use(profile_dir: str) -> bool:
    """检测浏览器 Profile 是否被锁定（浏览器正在使用）"""
    lock_file = Path(profile_dir) / "SingletonLock"
    if not lock_file.exists():
        return False
    try:
        import fcntl
        fd = os.open(str(lock_file), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            return False
        except (IOError, OSError):
            os.close(fd)
            return True
    except (ImportError, OSError):
        return True


def _find_available_port(start=9222):
    """找一个可用端口"""
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


MAX_LOGIN_WAIT = 180
LOGIN_POLL_INTERVAL = 3


def _has_login_cookies(cookies: list) -> bool:
    """检测 Cookie 列表中是否包含真正的登录态（CDP 浏览器端检测）

    sessionid / sessionid_ss / sid_guard 是真正登录后才会出现的 Cookie。
    odin_tt / passport_csrf_token 是所有访客（含未登录）都有的跟踪 Cookie，
    不能用来判断登录态。
    """
    cookie_names = {c.get("name", "") for c in cookies}
    matched = cookie_names & set(REAL_LOGIN_KEYS)
    return len(matched) >= 1


def is_cookie_logged_in(cookie_str: str) -> bool:
    """验证 Cookie 字符串是否包含真正的抖音登录态

    sessionid / sid_guard 是真正登录后才出现的。
    odin_tt / passport_csrf_token 是匿名访客也有的，不算登录。
    """
    if not cookie_str:
        return False
    return any(k in cookie_str for k in REAL_LOGIN_KEYS)


def extract_with_cdp(domain: str = "douyin.com",
                     wait_for_login: bool = True,
                     max_wait: int = MAX_LOGIN_WAIT,
                     progress_callback=None) -> Optional[str]:
    """策略1: CDP 协议 — Playwright 连接系统浏览器提取 Cookie

    两种模式:
    - wait_for_login=False (快速): 使用用户真实浏览器 Profile，提取已登录 Cookie
    - wait_for_login=True (交互): 使用临时 Profile，弹出浏览器等待用户手动登录

    借鉴 MediaCrawler: 通过 Chrome DevTools Protocol 连接浏览器，
    让浏览器自行解密 Cookie 后返回。不需要管理员权限！
    """
    browsers = _find_system_browser()
    if not browsers:
        logger.warning("未找到 Chrome/Edge 浏览器")
        return None

    real_profiles = _find_real_profiles() if not wait_for_login else []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright 未安装: pip install playwright")
        return None

    # ── 快速模式: 尝试使用真实 Profile ──
    if not wait_for_login and real_profiles:
        for profile_dir, profile_browser, user_data_dir in real_profiles:
            if _is_browser_profile_in_use(user_data_dir):
                logger.debug(f"  {profile_browser} Profile 正在使用中，跳过")
                continue

            matching_browsers = [(p, n) for p, n in browsers if n == profile_browser]
            if not matching_browsers:
                continue

            browser_path, browser_name = matching_browsers[0]
            debug_port = _find_available_port()
            logger.info(f"CDP: 从 {browser_name} 真实 Profile 提取...")

            try:
                proc = subprocess.Popen(
                    [browser_path,
                     f"--remote-debugging-port={debug_port}",
                     f"--user-data-dir={user_data_dir}",
                     f"--profile-directory={Path(profile_dir).name}",
                     "--no-first-run", "--headless=new",
                     "--window-size=1280,800"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(4)

                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{debug_port}")
                    contexts = browser.contexts
                    context = contexts[0] if contexts else browser.new_context()
                    page = context.new_page()
                    try:
                        page.goto(f"https://www.{domain}/", timeout=20000,
                                  wait_until="domcontentloaded")
                    except Exception:
                        pass
                    cookies = context.cookies()
                    result = _collect_douyin_cookies(context, page, domain)
                    page.close()
                    browser.close()
                proc.terminate()

                if result:
                    cookie_str = "; ".join(f"{c['name']}={c['value']}"
                                           for c in result)
                    if is_cookie_logged_in(cookie_str):
                        logger.info(f"✓ CDP 从 {browser_name} 真实 Profile 提取 {len(result)} 个 Cookie")
                        return cookie_str
                    else:
                        logger.debug(f"  {browser_name} 真实 Profile 未包含登录态")
            except Exception as e:
                logger.debug(f"CDP 真实 Profile({browser_name}): {e}")
            finally:
                try:
                    proc.terminate()
                except Exception:
                    pass

    # ── 交互模式: 临时 Profile + 登录等待 ──
    for browser_path, browser_name in browsers:
        debug_port = _find_available_port()
        logger.info(f"CDP: 启动 {browser_name} (端口 {debug_port})...")

        # 每个浏览器使用独立的临时 Profile，避免串 Cookie
        safe_name = browser_name.lower().replace(" ", "_")
        persist_dir = Path(tempfile.gettempdir()) / f"douyin_cdp_{safe_name}"
        persist_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(persist_dir)

        try:
            proc = subprocess.Popen(
                [
                    browser_path,
                    f"--remote-debugging-port={debug_port}",
                    f"--user-data-dir={user_data_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                    "--disable-extensions",
                    "--window-size=1280,800",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            time.sleep(3)

            with sync_playwright() as p:
                try:
                    browser = p.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{debug_port}"
                    )
                except Exception as e:
                    logger.warning(f"CDP 连接失败 ({browser_name}): {e}")
                    proc.terminate()
                    continue

                contexts = browser.contexts
                if not contexts:
                    context = browser.new_context()
                else:
                    context = contexts[0]

                page = context.new_page()

                try:
                    page.goto(f"https://www.{domain}/", timeout=15000,
                              wait_until="domcontentloaded")
                except Exception:
                    pass

                if wait_for_login:
                    all_cookies = _wait_for_login_and_capture(
                        context, page, domain, max_wait, browser_name, progress_callback
                    )
                else:
                    time.sleep(3)
                    all_cookies = _collect_douyin_cookies(context, page, domain)

                page.close()
                browser.close()

            proc.terminate()

            if all_cookies:
                cookie_str = "; ".join(f"{c['name']}={c['value']}"
                                       for c in all_cookies)
                if not is_cookie_logged_in(cookie_str):
                    logger.warning(f"CDP({browser_name}): 提取的 Cookie 未包含登录态，已丢弃")
                    logger.warning("  请确保在弹出的浏览器中完成登录后重试")
                    continue
                logger.info(f"✓ CDP 从 {browser_name} 提取了 {len(all_cookies)} 个 Cookie (已登录)")
                return cookie_str
            else:
                logger.info(f"CDP({browser_name}): 未获取到有效 Cookie")

        except Exception as e:
            logger.warning(f"CDP({browser_name}) 异常: {e}")
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

    return None


def _wait_for_login_and_capture(context, page, domain: str, max_wait: int,
                                browser_name: str, progress_callback=None) -> list:
    """循环等待用户登录，检测到登录态后抓取 Cookie"""
    logger.info("=" * 50)
    logger.info(f"  请在弹出的 {browser_name} 窗口中登录抖音")
    logger.info(f"  程序会自动检测登录状态 (最长等待 {max_wait}s)")
    logger.info("  登录成功后浏览器会自动关闭并提取 Cookie")
    logger.info("=" * 50)

    if progress_callback:
        progress_callback("waiting", "请在浏览器中登录抖音...")

    elapsed = 0
    while elapsed < max_wait:
        time.sleep(LOGIN_POLL_INTERVAL)
        elapsed += LOGIN_POLL_INTERVAL

        try:
            page.evaluate("1")
        except Exception:
            pass

        cookies = context.cookies()
        if _has_login_cookies(cookies):
            logger.info(f"✓ 检测到登录态! (已等待 {elapsed}s)")
            if progress_callback:
                progress_callback("logged_in", "登录检测成功，正在抓取 Cookie...")

            # 登录后刷新首页确保 Cookie 完整（用 domcontentloaded 避免 networkidle 超时）
            time.sleep(2)
            try:
                page.goto(f"https://www.{domain}/", timeout=15000,
                          wait_until="domcontentloaded")
                time.sleep(2)
            except Exception:
                logger.warning("  刷新页面超时，继续提取当前 Cookie...")

            cookies = context.cookies()
            result = _collect_douyin_cookies(context, page, domain)
            logger.info(f"  已抓取 {len(result)} 个 Cookie")
            return result

        remaining = max_wait - elapsed
        if elapsed % 15 == 0 or elapsed <= LOGIN_POLL_INTERVAL:
            logger.info(f"  等待登录中... (已等待 {elapsed}s, 剩余 {remaining}s)")

    logger.warning(f"登录等待超时 ({max_wait}s)，未检测到登录态")
    logger.warning("  请重新运行并确保在弹出的浏览器中完成登录")
    return []


def _collect_douyin_cookies(context, page, domain: str) -> list:
    """从当前上下文收集 douyin.com 相关 Cookie"""
    try:
        cookies = context.cookies()
    except Exception:
        cookies = []

    douyin_cookies = [c for c in cookies if domain in c.get("domain", "")]
    if douyin_cookies:
        return douyin_cookies

    douyin_cookies = [c for c in cookies
                      if any(d in c.get("domain", "")
                             for d in [domain, "douyin.com", ".douyin.com"])]
    if douyin_cookies:
        return douyin_cookies

    return cookies


def extract_with_rookiepy(domain: str = "douyin.com") -> Optional[str]:
    """策略2: rookiepy 直接读取浏览器加密 Cookie（需管理员权限）"""
    try:
        from rookiepy import edge, chrome, brave

        for browser_func, name in [(edge, "Edge"), (chrome, "Chrome"), (brave, "Brave")]:
            try:
                raw = browser_func(domains=[domain])
                if raw:
                    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in raw)
                    logger.info(f"✓ rookiepy 从 {name} 提取了 {len(raw)} 个 Cookie")
                    return cookie_str
            except RuntimeError as e:
                msg = str(e)
                if "admin" in msg.lower() or "appbound" in msg.lower():
                    logger.debug(f"rookiepy({name}): 需要管理员权限")
                else:
                    logger.debug(f"rookiepy({name}): {e}")
            except Exception:
                pass
    except ImportError:
        logger.debug("rookiepy 未安装，跳过")
    except Exception as e:
        logger.debug(f"rookiepy 异常: {e}")
    return None


def extract_from_clipboard() -> Optional[str]:
    """从剪贴板提取纯 Cookie 字符串

    支持三种格式:
    1. 纯 Cookie 字符串: "a=1; b=2; ..."
    2. cURL 命令 (F12 → Copy as cURL): curl '...' -H 'Cookie: ...'
    3. Netscape 格式
    """
    try:
        text = subprocess.check_output(
            ["powershell", "-command", "Get-Clipboard"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).strip()
    except Exception:
        text = ""

    if not text:
        return None

    # 格式1: cURL 命令 → 提取 Cookie: 头
    if text.startswith("curl ") or "curl " in text[:10]:
        import re
        # 匹配 -H 'Cookie: xxx' 或 -H "Cookie: xxx" 或 --header 'Cookie: xxx'
        m = re.search(
            r"""-H\s+['\"]Cookie:\s*([^'\"]+)['\"]""",
            text, re.IGNORECASE
        )
        if not m:
            m = re.search(
                r"""--header\s+['\"]Cookie:\s*([^'\"]+)['\"]""",
                text, re.IGNORECASE
            )
        if m:
            cookie_str = m.group(1).strip()
            logger.info(f"✓ 从剪贴板 curl 命令提取 Cookie ({len(cookie_str)} 字符)")
            return cookie_str
        # fallback: 尝试从 -b 'cookie' 或 --cookie 提取
        m = re.search(r"""-b\s+['\"]([^'\"]+)['\"]""", text)
        if m:
            cookie_str = m.group(1).strip()
            logger.info(f"✓ 从剪贴板 curl -b 提取 Cookie ({len(cookie_str)} 字符)")
            return cookie_str

    # 格式2: Netscape 格式 ─ 跳过
    if "# Netscape HTTP Cookie File" in text:
        logger.debug("剪贴板为 Netscape cookie 格式，跳过")
        return None

    # 格式3: 纯 Cookie 字符串检测
    session_keys = ["sessionid", "sid_guard", "passport_csrf_token", "odin_tt", "s_v_web_id"]
    found = sum(1 for k in session_keys if k in text)
    if found >= 2:
        logger.info(f"✓ 从剪贴板识别到 Cookie ({len(text)} 字符)")
        return text

    if "=" in text and ";" in text and len(text) > 200 and len(text) < 10000:
        logger.info(f"✓ 从剪贴板检测到可能的 Cookie ({len(text)} 字符)")
        return text

    return None


def extract_cookie_from_browser(wait_for_login: bool = False,
                                 max_wait: int = MAX_LOGIN_WAIT,
                                 progress_callback=None) -> Optional[str]:
    """主入口: 依次尝试多种策略提取 Cookie

    快速模式 (wait_for_login=False, 默认):
      1. 剪贴板 → 无需管理员，最可靠的 API Cookie 来源
      2. rookiepy → 读真实浏览器数据库，需管理员
      3. CDP 快速 → 最后一招，Cookie 可能无法用于 API

    交互模式 (wait_for_login=True):
      CDP 弹出浏览器等待手动登录 → 抓取 Cookie → API 自检
    """
    if wait_for_login:
        return extract_cookie_interactive(
            max_wait=max_wait, progress_callback=progress_callback)

    # ── 快速模式 ──
    # 策略1: 剪贴板 — 最可靠的非管理员方案
    logger.info("正在从剪贴板检测 Cookie...")
    result = extract_from_clipboard()
    if result and is_cookie_logged_in(result):
        logger.info("✓ 剪贴板 Cookie 有效")
        return result

    # 策略2: rookiepy — 读真实浏览器数据库
    logger.info("剪贴板无有效 Cookie，尝试 rookiepy...")
    result = extract_with_rookiepy()
    if result and is_cookie_logged_in(result):
        return result

    # 策略3: CDP 快速（最后兜底，Cookie 可能仅限浏览器内有效）
    logger.info("rookiepy 失败，尝试 CDP 快速提取...")
    result = extract_with_cdp(wait_for_login=False)
    if result and is_cookie_logged_in(result):
        return result

    # 策略4: 匿名访客 Cookie（无登录兜底 — 访问 douyin.com 获取基础 Cookie）
    logger.info("以上策略均失败，尝试无登录兜底...")
    logger.info("  ⚠ 注意: 搜索接口需要登录，匿名 Cookie 可能仅限公开页面")
    result = get_guest_cookies()
    if result:
        logger.info("✓ 获取到匿名访客 Cookie（但搜索可能仍需登录）")
        return result

    return None


def extract_cookie_interactive(max_wait: int = MAX_LOGIN_WAIT,
                               progress_callback=None) -> Optional[str]:
    """交互式提取：弹出浏览器等待用户手动登录后抓取 Cookie

    这是 GUI「浏览器登录提取」按钮调用的入口。
    仅使用 CDP 策略（不需要管理员权限），会弹出 Chrome/Edge 窗口
    等待用户在浏览器中完成登录后自动抓取。

    注意: CDP 提取的 Cookie 是浏览器会话级，可能无法用于 API 调用。
          抓取后会进行 API 自检，失败时提示用户使用剪贴板。

    Args:
        max_wait: 登录最长等待秒数 (默认 180s)
        progress_callback: 进度回调 callable(status, message)

    Returns:
        提取到的登录态 Cookie 字符串，失败返回 None
    """
    result = extract_with_cdp(
        wait_for_login=True,
        max_wait=max_wait,
        progress_callback=progress_callback,
    )
    if not result:
        return None

    logger.info("正在进行 API 有效性自检...")
    if _run_api_check(result):
        logger.info("✓ Cookie API 自检通过")
        return result
    else:
        logger.warning("⚠ Cookie 已抓取但 API 自检未通过")
        logger.warning("  CDP Cookie 可能仅限浏览器内有效")
        logger.warning("  推荐: F12 → Network → 右键 → Copy as cURL → 点 📋粘贴")
        return result


def verify_cookie_api(cookie_str: str = None) -> bool:
    """验证 Cookie 是否能通过抖音搜索 API

    Args:
        cookie_str: Cookie 字符串，为 None 则从 .env 加载
    """
    if cookie_str is None:
        from config import load_cookie
        try:
            cookie_str = load_cookie()["cookie_str"]
        except Exception:
            return False
    import sys
    if getattr(sys, 'frozen', False):
        return _sync_api_check(cookie_str)
    return _run_api_check(cookie_str)


def _run_api_check(cookie_str: str) -> bool:
    """内部: 用 httpx 直接调用搜索 API 验证 Cookie"""
    import asyncio
    try:
        return asyncio.run(_async_api_check(cookie_str))
    except RuntimeError:
        # 已经在一个运行中的 event loop 里
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.ensure_future(_async_api_check(cookie_str))
            # 如果有上层 loop 在运行，用 create_task + 返回 False
            return False
        except RuntimeError:
            return False
    except Exception:
        return False


async def _async_api_check(cookie_str: str) -> bool:
    """异步 API 自检 — 最小请求验证 Cookie"""
    import httpx
    from config import COMMON_PARAMS, generate_ms_token, generate_webid, DEFAULT_USER_AGENT

    params = COMMON_PARAMS.copy()
    params["msToken"] = generate_ms_token()
    params["webid"] = generate_webid()
    params.update({"keyword": "test", "count": "1", "offset": "0",
                   "search_channel": "aweme_general", "search_source": "tab_search"})
    url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Cookie": cookie_str, "Referer": "https://www.douyin.com/",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=15) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.debug(f"API 自检: HTTP {resp.status_code}")
                return False
            data = resp.json()
            sc = data.get("status_code", -1)
            if sc == 0:
                return True
            logger.debug(f"API 自检: code={sc} msg={data.get('status_msg')}")
            return False
    except Exception as e:
        logger.debug(f"API 自检异常: {e}")
        return False


def _sync_api_check(cookie_str: str) -> bool:
    """同步 API 自检 — 用于 asyncio 不可用的环境（如 EXE GUI 线程）"""
    import httpx
    from config import COMMON_PARAMS, generate_ms_token, generate_webid, DEFAULT_USER_AGENT

    params = COMMON_PARAMS.copy()
    params["msToken"] = generate_ms_token()
    params["webid"] = generate_webid()
    params.update({"keyword": "test", "count": "1", "offset": "0",
                   "search_channel": "aweme_general", "search_source": "tab_search"})
    url = "https://www.douyin.com/aweme/v1/web/general/search/single/"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Cookie": cookie_str, "Referer": "https://www.douyin.com/",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(verify=False, timeout=15) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.debug(f"API 自检(同步): HTTP {resp.status_code}")
                return False
            data = resp.json()
            sc = data.get("status_code", -1)
            if sc == 0:
                return True
            logger.debug(f"API 自检(同步): code={sc} msg={data.get('status_msg')}")
            return False
    except Exception as e:
        logger.debug(f"API 自检(同步)异常: {e}")
        return False


def get_guest_cookies() -> Optional[str]:
    """无登录兜底方案：访问 douyin.com 获取匿名访客 Cookie

    抖音会为所有访客（含未登录）生成 odin_tt、passport_csrf_token、ttwid 等
    设备级 Cookie。这些 Cookie 虽然不能用于搜索接口（search API 需要登录），
    但可以用于部分公开 API（如视频详情、用户主页等）。

    调用方应使用 verify_cookie_api() 验证返回的 Cookie 是否可用于搜索。

    Returns:
        匿名访客 Cookie 字符串，失败返回 None
    """
    import asyncio
    try:
        return asyncio.run(_async_get_guest())
    except Exception:
        return None


async def _async_get_guest() -> Optional[str]:
    import httpx
    from urllib.parse import quote

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        async with httpx.AsyncClient(verify=False, timeout=20, follow_redirects=True) as client:
            resp = await client.get("https://www.douyin.com/", headers=headers)
            if resp.status_code != 200:
                logger.warning(f"访问 douyin.com 返回 {resp.status_code}")
                return None

            cookies = []
            for name, value in resp.cookies.items():
                cookies.append(f"{name}={value}")
            # 从 Set-Cookie header 也收集
            for h_name, h_value in resp.headers.multi_items():
                if h_name.lower() == "set-cookie":
                    for part in h_value.split("; "):
                        if "=" in part:
                            cookies.append(part)

            if not cookies:
                logger.warning("douyin.com 未返回任何 Cookie")
                return None

            cookie_str = "; ".join(dict.fromkeys(cookies))  # 去重
            logger.info(f"✓ 获取到 {len(cookies)} 个匿名访客 Cookie")
            return cookie_str

    except Exception as e:
        logger.warning(f"获取匿名访客 Cookie 失败: {e}")
        return None


def save_cookie_to_env(cookie_str: str, env_path: Optional[str] = None,
                       force: bool = False) -> bool:
    """将 Cookie 写入 .env 文件

    Args:
        cookie_str: Cookie 字符串
        env_path: .env 文件路径
        force: 强制写入，跳过登录态验证（仅用于用户明确粘贴的场景）

    Returns:
        bool: 是否写入成功
    """
    if not force and not is_cookie_logged_in(cookie_str):
        logger.warning("拒绝写入 .env: Cookie 未包含登录态")
        logger.warning("  请确保已登录抖音后再提取 Cookie")
        return False

    if not force:
        logger.info("API 自检中...")
        import sys as _sys
        ok = _sync_api_check(cookie_str) if getattr(_sys, 'frozen', False) else _run_api_check(cookie_str)
        if not ok:
            logger.warning("⚠ API 自检未通过，Cookie 可能无法用于搜索")
            logger.warning("  仍将写入 .env 但建议用 F12 DevTools 重新获取")

    if env_path is None:
        import sys
        if getattr(sys, 'frozen', False):
            env_path = Path(sys.executable).resolve().parent / ".env"
        else:
            env_path = Path(__file__).resolve().parent.parent / ".env"
    env_path = Path(env_path)
    try:
        content = f"DY_COOKIE='{cookie_str}'\n"
        env_path.write_text(content, encoding="utf-8")
        logger.info(f"Cookie 已写入 {env_path}")
        return True
    except Exception as e:
        logger.error(f"写入 .env 失败: {e}")
        return False


if __name__ == "__main__":
    print("正在提取抖音 Cookie ...")
    result = extract_cookie_from_browser()
    if result:
        print(f"✓ 提取成功！共 {len(result)} 字符")
        save_cookie_to_env(result, force=True)
    else:
        print("✗ 未获取到登录态 Cookie")
        print("  方案1: pip install playwright (无需管理员)")
        print("  方案2: pip install rookiepy + 以管理员运行")
        print("  方案3: F12→Network→复制Cookie→本脚本自动读剪贴板")
