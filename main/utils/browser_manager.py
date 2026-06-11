"""浏览器 Cookie 管理器 — Playwright 持久化真实 Profile

与之前 CDP subprocess 的根本区别:
- CDP subprocess: 临时 Profile → 会话级 Cookie → API 不可用
- launch_persistent_context: 永久 Profile → 数据库级 Cookie → API 可用

用法:
    async with BrowserCookieManager() as mgr:
        await mgr.ensure_logged_in()  # 弹出窗口等你登录 (仅第一次)
        cookie = mgr.get_cookie_str()  # 随时获取最新 Cookie
"""

import sys
from pathlib import Path
from typing import Optional, Callable

from utils.logger import logger

from config import REAL_LOGIN_KEYS


class BrowserCookieManager:
    """Playwright 持久化浏览器 Cookie 管理器

    维护一个长期运行的 Chromium 实例，使用真实 Profile 目录。
    Cookie 存在真实的 SQLite 数据库中，与普通 Chrome 完全一致，
    可以直接用于抖音 HTTP API 调用。
    """

    def __init__(self, profile_dir: Optional[str] = None, headless: bool = False):
        import tempfile
        self._profile_dir = str(profile_dir or (
                Path(tempfile.gettempdir()) / "douyin_browser_profile"))
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    @property
    def is_logged_in(self) -> bool:
        """当前浏览器中是否已登录抖音"""
        return self._logged_in

    @property
    def is_running(self) -> bool:
        """浏览器是否正在运行"""
        return self._context is not None

    async def _check_login(self) -> bool:
        if self._context is None:
            return False
        # 方式1: Playwright context.cookies()
        cookies = await self._context.cookies()
        douyin_cookies = [c for c in cookies
                          if "douyin.com" in c.get("domain", "")
                          or c.get("domain") == ".douyin.com"]
        cookie_names = {c.get("name", "") for c in douyin_cookies}
        matched = cookie_names & set(REAL_LOGIN_KEYS)

        # 方式2: 兜底 — document.cookie
        if not matched and self._page:
            try:
                doc_cookie = await self._page.evaluate("document.cookie")
                for pair in doc_cookie.split("; "):
                    if "=" in pair:
                        k = pair.split("=")[0]
                        if k in REAL_LOGIN_KEYS:
                            cookie_names.add(k)
                            matched = cookie_names & set(REAL_LOGIN_KEYS)
            except Exception:
                pass

        logger.debug(f"_check_login: cookies={sorted(cookie_names)}, matched={matched}")
        self._logged_in = len(matched) >= 1
        if self._logged_in:
            # 直接在此构建 Cookie 字符串并写入 .env
            self._cached_cookies = douyin_cookies
            self._save_to_env_from(douyin_cookies)
        return self._logged_in

    def _save_to_env_from(self, cookies: list):
        """用已获取的 cookies 列表写入 .env（避免再调 get_cookie_str 的 event loop 问题）"""
        try:
            douyin = [c for c in cookies if "douyin.com" in c.get("domain", "")
                      or c.get("domain") == ".douyin.com"]
            if not douyin:
                douyin = cookies
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in douyin)
            if not cookie_str:
                return
            from utils.cookie_util import is_cookie_logged_in, save_cookie_to_env
            if not is_cookie_logged_in(cookie_str):
                return
            save_cookie_to_env(cookie_str)
            logger.info("✓ 浏览器 Cookie 已自动写入 .env")
        except Exception as e:
            logger.debug(f"自动写入 .env 失败: {e}")

    def get_cookie_str(self, domain: str = "douyin.com") -> str:
        """获取 Cookie 字符串 — 先尝试缓存，fallback 同步爬取"""
        if self._context is None:
            return ""
        cached = getattr(self, "_cached_cookies", None)
        if cached:
            douyin = [c for c in cached if domain in c.get("domain", "")
                      or c.get("domain") == f".{domain}"]
            if not douyin:
                douyin = cached
            return "; ".join(f"{c['name']}={c['value']}" for c in douyin)

        # fallback: 在新 event loop 中获取
        import asyncio
        async def _get():
            cookies = await self._context.cookies()
            douyin_cookies = [
                c for c in cookies
                if domain in c.get("domain", "") or c.get("domain") == f".{domain}"
            ]
            return "; ".join(f"{c['name']}={c['value']}" for c in (douyin_cookies or cookies))

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_get())
        # 在运行中的 loop 中 — 用 cached 返回（保证不阻塞）
        return ""

    def make_cookie_provider(self) -> Callable[[], str]:
        """返回一个 callable，供 DouyinEngine 在每次 API 请求前调用"""

        def _provider() -> str:
            return self.get_cookie_str()

        return _provider

    async def start(self, width: int = 1280, height: int = 800):
        """启动浏览器 (headless 时不可见)"""
        if self._context is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError("Playwright 未安装: pip install playwright && playwright install chromium")

        Path(self._profile_dir).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        launch_kwargs = {
            "user_data_dir": self._profile_dir,
            "headless": self._headless,
            "viewport": {"width": width, "height": height},
            "args": [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-extensions",
                "--disable-blink-features=AutomationControlled",
            ],
        }

        last_error = None
        for strategy in ["playwright", "chrome", "msedge"]:
            try:
                if strategy != "playwright":
                    launch_kwargs["channel"] = strategy
                self._context = await self._playwright.chromium.launch_persistent_context(
                    **launch_kwargs)
                logger.info(f"BrowserCookieManager: 使用 {strategy}")
                break
            except Exception as e:
                last_error = e
                launch_kwargs.pop("channel", None)
                logger.debug(f"  {strategy} 不可用: {e}")
        else:
            exe_path = _find_browser_executable()
            logger.info(f"BrowserCookieManager: 尝试 executable_path={exe_path}")
            if exe_path:
                launch_kwargs["executable_path"] = exe_path
                try:
                    self._context = await self._playwright.chromium.launch_persistent_context(
                        **launch_kwargs)
                    logger.info(f"BrowserCookieManager: 使用 {exe_path}")
                except Exception as e2:
                    raise RuntimeError(f"无法启动浏览器 (channel={last_error}, exe={e2})")
            else:
                raise RuntimeError(f"无法启动浏览器 (channel={last_error}, 未找到系统浏览器)")

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

        # 导航到 douyin.com 加载首页 Cookie
        try:
            await self._page.goto("https://www.douyin.com/",
                                  timeout=15000, wait_until="domcontentloaded")
            await self._page.wait_for_timeout(3000)
        except Exception:
            pass

        await self._check_login()

        if not self._logged_in:
            # debug: 打印当前所有 cookie 名字
            all_cookies = await self._context.cookies()
            cookie_names = sorted({c.get("name", "") for c in all_cookies})
            logger.debug(f"当前浏览器 Cookie ({len(all_cookies)} 个): {cookie_names}")

        logger.info("BrowserCookieManager 已启动"
                     + (" (已登录)" if self._logged_in else " (未登录)"))

    async def ensure_logged_in(self, max_wait: int = 300,
                               progress_callback: Optional[Callable] = None) -> bool:
        """确保浏览器已登录抖音。未登录时弹出可见窗口等待。

        返回 True 表示已登录或等待后登录成功。
        """
        if await self._check_login():
            return True

        if self._headless:
            logger.info("浏览器为 headless 模式，切换为可见窗口...")
            await self.stop()
            self._headless = False
            await self.start()

        logger.info("=" * 50)
        logger.info("  请在弹出的 Chromium 窗口中登录抖音")
        logger.info(f"  程序会自动检测登录状态 (最长等待 {max_wait}s)")
        logger.info("  登录后 Cookie 持久保存，下次启动无需重新登录")
        logger.info("=" * 50)

        if progress_callback:
            progress_callback("waiting", "请在浏览器窗口中登录抖音...")

        try:
            await self._page.goto("https://www.douyin.com/",
                                  timeout=15000, wait_until="domcontentloaded")
        except Exception:
            pass

        elapsed = 0
        while elapsed < max_wait:
            await self._page.wait_for_timeout(3000)
            elapsed += 3

            try:
                await self._page.evaluate("1")
            except Exception:
                pass

            if await self._check_login():
                logger.info(f"✓ 检测到登录态! (已等待 {elapsed}s)")
                if progress_callback:
                    progress_callback("logged_in", "登录成功！Cookie 已持久保存")
                return True

            remaining = max_wait - elapsed
            if elapsed % 15 == 0 or elapsed == 3:
                logger.info(f"  等待登录中... (已等待 {elapsed}s, 剩余 {remaining}s)")

        logger.warning(f"登录等待超时 ({max_wait}s)")
        return False

    async def refresh(self):
        """刷新页面，确保 Cookie 最新"""
        if self._page:
            try:
                await self._page.goto("https://www.douyin.com/",
                                      timeout=15000, wait_until="domcontentloaded")
                await self._page.wait_for_timeout(2000)
                await self._check_login()
            except Exception:
                pass

    async def stop(self):
        """关闭浏览器"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


def _find_browser_executable() -> str:
    """在系统上查找 Chrome/Edge 的可执行文件路径"""
    import os as _os
    local = _os.getenv("LOCALAPPDATA", "")
    roaming = _os.getenv("APPDATA", "")
    program_files = _os.getenv("ProgramFiles", "C:\\Program Files")
    program_files_x86 = _os.getenv("ProgramFiles(x86)", "C:\\Program Files (x86)")

    candidates = [
        _os.path.join(local, "Microsoft", "Edge", "Application", "msedge.exe"),
        _os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
        _os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
        _os.path.join(roaming, "Google", "Chrome", "Application", "chrome.exe"),
        _os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        _os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if _os.path.isfile(path):
            return path
    return ""


def _ensure_chromium_installed():
    """确保 Playwright Chromium 已安装，未安装则自动安装"""
    import subprocess, os
    # 检查 Playwright Chromium 是否已安装
    base = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                        "ms-playwright")
    for ver_dir in os.listdir(base) if os.path.isdir(base) else []:
        chrome_path = os.path.join(base, ver_dir, "chrome-win64", "chrome.exe")
        if os.path.exists(chrome_path):
            return True  # 已安装，无需操作

    logger.info("Playwright Chromium 未安装，正在自动安装...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.warning(f"Playwright Chromium 安装失败: {result.stderr[:200]}")
            logger.warning("将尝试使用系统 Chrome/Edge")
            return False
        logger.info("✓ Playwright Chromium 安装完成")
        return True
    except Exception as e:
        logger.warning(f"Playwright Chromium 安装异常: {e}")
        return False
