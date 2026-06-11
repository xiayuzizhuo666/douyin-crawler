import os
import random
import string
import sys
from pathlib import Path

from dotenv import load_dotenv

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

# ============================================================
# Cookie 管理
# ============================================================

def trans_cookies(cookie_str: str) -> dict:
    """将 Cookie 字符串解析为字典"""
    cookies = {}
    for item in cookie_str.split("; "):
        try:
            key, *rest = item.split("=")
            cookies[key] = "=".join(rest)
        except Exception:
            continue
    return cookies


def load_cookie() -> dict:
    """从 .env 文件加载 Cookie 并解析为字典

    每次调用都重新读取 .env 文件，确保获取最新写入的 Cookie。

    Returns:
        dict: {"cookie_str": "原始Cookie字符串", "cookie_dict": {...}, "s_v_web_id": "..."}
    """
    load_dotenv(BASE_DIR / ".env", override=True)
    cookie_str = os.getenv("DY_COOKIE", "").strip().strip("'\"")

    if not cookie_str:
        raise ValueError(
            "未找到 Cookie。请：\n"
            "  1. 点击 GUI 中的\"登录提取\"按钮，在弹出的浏览器中登录抖音\n"
            "  2. 或手动填写 .env 中的 DY_COOKIE（F12 → Network → 复制 Cookie）"
        )

    cookie_dict = trans_cookies(cookie_str)

    return {
        "cookie_str": "; ".join([f"{k}={v}" for k, v in cookie_dict.items()]),
        "cookie_dict": cookie_dict,
        "s_v_web_id": cookie_dict.get("s_v_web_id", ""),
    }


def extract_s_v_web_id(cookie_dict: dict) -> str:
    """从 Cookie 字典中提取 s_v_web_id"""
    return cookie_dict.get("s_v_web_id", "")


# ============================================================
# 请求配置
# ============================================================

REQUEST_TIMEOUT = 30

SPEED_PROFILES = {
    "安全": {
        "search":  (3.0, 5.0),
        "user":    (3.0, 8.0),
        "post":    (1.0, 3.0),
    },
    "快速": {
        "search":  (1.5, 3.0),
        "user":    (2.0, 4.0),
        "post":    (0.8, 1.5),
    },
    "极速": {
        "search":  (0.8, 1.5),
        "user":    (1.0, 2.5),
        "post":    (0.3, 0.8),
    },
}
DEFAULT_SPEED_MODE = "安全"

MULTI_ROUND_SEARCH = False
MULTI_ROUND_SORT_TYPES = [1, 2]

SKIP_DETAIL_API = False

REAL_LOGIN_KEYS = ["sessionid", "sessionid_ss", "sid_guard"]

GUEST_KEYS = ["odin_tt", "passport_csrf_token", "s_v_web_id", "ttwid"]

# ============================================================
# 采集配置
# ============================================================

SCAN_POST_COUNT = 10
SEARCH_SORT_TYPE = 1
SEARCH_PUBLISH_TIME = 180
SEARCH_MAX_COUNT = 200
MIN_FOLLOWER_COUNT = 0
MAX_CONCURRENCY = 3

# ============================================================
# 输出配置
# ============================================================

OUTPUT_DIR = str(BASE_DIR / "output")
OUTPUT_FORMAT = "xlsx"

# ============================================================
# User-Agent 配置
# ============================================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

DEFAULT_USER_AGENT = USER_AGENTS[0]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


# ============================================================
# msToken 生成
# ============================================================

def generate_ms_token(length: int = 107) -> str:
    base_str = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    return "".join(random.choice(base_str) for _ in range(length))


# ============================================================
# webid 生成
# ============================================================

def generate_webid(length: int = 19) -> str:
    chars = "0123456789"
    return "".join(random.choice(chars) for _ in range(length))


# ============================================================
# 公共请求参数
# ============================================================

COMMON_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "update_version_code": "170400",
    "pc_client_type": "1",
    "version_code": "290100",
    "version_name": "29.1.0",
    "cookie_enabled": "true",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Edge",
    "browser_version": "130.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "engine_version": "130.0.0.0",
    "os_name": "Windows",
    "os_version": "10",
    "cpu_core_num": "12",
    "device_memory": "8",
    "platform": "PC",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "100",
}
