"""抖音 HTTP 请求引擎 — 对齐 TikTokDownloader + DouYin_Spider"""

import asyncio
import json
import random
from urllib.parse import quote, urlencode
from typing import Optional, Dict, Callable

import httpx

from config import (
    COMMON_PARAMS,
    DEFAULT_USER_AGENT,
    USER_AGENTS,
    REQUEST_TIMEOUT,
    generate_ms_token,
    generate_webid,
    extract_s_v_web_id,
)
from sign.abogus import ABogus
from utils.logger import logger


HEADERS_TEMPLATE = {
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "Priority": "u=1, i",
}


class DouyinEngine:

    def __init__(self, cookie_str: str = None,
                 cookie_provider: Optional[Callable[[], str]] = None,
                 proxies: Optional[Dict] = None):
        """请求引擎

        Args:
            cookie_str: 静态 Cookie 字符串 (优先)
            cookie_provider: 动态 Cookie 供应函数，每次请求前调用 (兜底)
            proxies: HTTP 代理
        """
        self._cookie_str = cookie_str or ""
        self._cookie_provider = cookie_provider
        self._refresh_cookie_dict()

        self.proxies = proxies
        self._client: Optional[httpx.AsyncClient] = None

        self._ms_token = generate_ms_token()
        self._webid = generate_webid()
        self._verify_fp = extract_s_v_web_id(self.cookie_dict)

        self._current_ua = DEFAULT_USER_AGENT
        self._ab = ABogus(user_agent=self._current_ua)

    def _refresh_cookie_dict(self):
        self.cookie_dict = {}
        for item in self._cookie_str.split("; "):
            try:
                k, *v = item.split("=")
                self.cookie_dict[k] = "=".join(v)
            except Exception:
                continue

    @property
    def cookie_str(self) -> str:
        """获取当前有效 Cookie：优先 provider，fallback 静态值"""
        if self._cookie_provider:
            fresh = self._cookie_provider()
            if fresh:
                return fresh
        return self._cookie_str

    @cookie_str.setter
    def cookie_str(self, value: str):
        self._cookie_str = value
        self._refresh_cookie_dict()

    def rotate_ua(self):
        self._current_ua = random.choice(USER_AGENTS)
        self._ab = ABogus(user_agent=self._current_ua)
        logger.debug(f"UA 轮换: {self._current_ua[:60]}...")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                proxy=self.proxies,
                verify=False,
                follow_redirects=True,
            )
        return self._client

    def _build_headers(self, referer: Optional[str] = None) -> dict:
        headers = HEADERS_TEMPLATE.copy()
        headers["User-Agent"] = self._current_ua
        headers["Cookie"] = self.cookie_str
        if referer:
            headers["Referer"] = quote(referer, safe=":/?=&")
        return headers

    def _build_params(self, api_params: Optional[dict] = None) -> dict:
        """合并公共参数 — 对齐 TikTokDownloader template"""
        params = COMMON_PARAMS.copy()
        params["msToken"] = self._ms_token
        params["webid"] = self._webid
        if self._verify_fp:
            params["verifyFp"] = self._verify_fp
            params["fp"] = self._verify_fp
        if api_params:
            params.update(api_params)
        return params

    def _inject_abogus(self, params: dict) -> str:
        """注入 a_bogus — 抖音 web API 当前不强制校验 a_bogus，此方法预留备用。
        如需启用，将 get()/post() 中的 params 传递改为先用此方法构造完整 URL。"""
        qs = urlencode(params, quote_via=quote)
        ab_value = self._ab.get_value(qs, "GET")
        return f"{qs}&a_bogus={ab_value}"

    async def get(self, api: str, params: Optional[dict] = None,
                  referer: Optional[str] = None) -> dict:
        client = await self._get_client()
        all_params = self._build_params(params)

        for attempt in range(3):
            headers = self._build_headers(referer)
            url = f"https://www.douyin.com{api}"
            response = await client.get(url, params=all_params, headers=headers)

            if response.status_code == 444:
                wait = 5 * (2 ** attempt)
                logger.warning(f"收到 444 (第{attempt+1}次重试)，{wait}秒后重试...")
                self.rotate_ua()
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()

            try:
                result = response.json()
            except json.JSONDecodeError:
                text = response.text[:500]
                if not text.strip():
                    return {}
                logger.error(f"JSON解析失败: {text}")
                raise

            sc = result.get("status_code")
            if sc == 8:
                raise Exception("Cookie 已过期或无效")
            if sc == 2483:
                raise Exception(f"需要登录: {result.get('status_msg', '请先登录')}")
            return result

        raise Exception("连续收到 3 次 444，抖音拒绝连接，请稍后重试")

    async def post(self, api: str, data: Optional[dict] = None,
                   params: Optional[dict] = None,
                   referer: Optional[str] = None) -> dict:
        client = await self._get_client()
        all_params = self._build_params(params)
        post_data_str = urlencode(data, quote_via=quote) if data else ""

        for attempt in range(3):
            headers = self._build_headers(referer)
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            url = f"https://www.douyin.com{api}"
            response = await client.post(url, params=all_params, data=post_data_str, headers=headers)

            if response.status_code == 444:
                wait = 5 * (2 ** attempt)
                logger.warning(f"收到 444 (第{attempt+1}次重试)，{wait}秒后重试...")
                self.rotate_ua()
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()

            try:
                result = response.json()
            except json.JSONDecodeError:
                text = response.text[:500]
                if not text.strip():
                    return {}
                logger.error(f"JSON解析失败: {text}")
                raise

            if result.get("status_code") == 8:
                raise Exception("Cookie 已过期或无效")
            if result.get("status_code") == 2483:
                raise Exception(f"需要登录: {result.get('status_msg', '请先登录')}")
            return result

        raise Exception("连续收到 3 次 444，抖音拒绝连接，请稍后重试")

    async def check_cookie_valid(self) -> bool:
        client = await self._get_client()
        headers = self._build_headers("https://www.douyin.com/")

        try:
            params = {"aid": "6383", "keyword": "test", "offset": "0",
                      "count": "1", "search_channel": "aweme_general"}
            response = await client.get(
                "https://www.douyin.com/aweme/v1/web/general/search/single/",
                params=params, headers=headers,
            )
            if response.status_code == 200:
                data = response.json()
                sc = data.get("status_code", -1)
                msg = data.get("status_msg", "")
                if sc == 0:
                    logger.info("Cookie 有效 ✓")
                    return True
                elif sc in (8, 2483, 2484, 2485):
                    logger.warning(f"Cookie 已过期 (code={sc}, msg={msg})")
                    return False
                else:
                    logger.warning(f"Cookie 状态异常 (code={sc}, msg={msg})")
                    return False
        except Exception:
            pass

        logger.warning("Cookie 可能已过期，继续尝试...")
        return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
