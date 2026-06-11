import asyncio
import functools
from random import uniform

from utils.logger import logger


async def random_delay(min_sec: float = 3.0, max_sec: float = 8.0):
    """每次接口调用前随机延迟"""
    delay = uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


def retry_on_failure(max_retries: int = 3, base_delay: float = 5.0):
    """指数退避重试装饰器"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt == max_retries - 1:
                        logger.error(f"重试{max_retries}次后仍然失败: {e}")
                        raise
                    wait = base_delay * (2 ** attempt)
                    logger.warning(f"第{attempt + 1}次失败，{wait:.0f}秒后重试: {e}")
                    await asyncio.sleep(wait)
            raise last_error
        return wrapper
    return decorator


class RateLimiter:
    """分级请求频率控制器（并发安全）

    使用 asyncio.Lock 确保多协程并发时不会同时请求，
    根据业务类型使用不同的延迟区间。
    可通过 apply_profile() 动态切换速度模式。
    """

    LIMITS = {
        "search":  (3.0, 5.0),
        "user":    (3.0, 8.0),
        "post":    (1.0, 3.0),
        "default": (3.0, 8.0),
    }

    def __init__(self):
        self._locks = {}

    def apply_profile(self, profile: dict):
        """应用速度模式配置"""
        for cat, (lo, hi) in profile.items():
            if cat in self.LIMITS:
                self.LIMITS[cat] = (float(lo), float(hi))

    def _get_lock(self, category: str) -> asyncio.Lock:
        if category not in self._locks:
            self._locks[category] = asyncio.Lock()
        return self._locks[category]

    async def wait(self, category: str = "default"):
        """在指定类别的请求前等待随机延迟（同一类别串行，不同类别可并发）"""
        lock = self._get_lock(category)
        async with lock:
            min_s, max_s = self.LIMITS.get(category, self.LIMITS["default"])
            delay = uniform(min_s, max_s)
            await asyncio.sleep(delay)


async def safe_execute(func, error_label: str = "", max_retries: int = 3):
    """安全执行异步函数：失败容错，不抛异常

    Args:
        func: 异步可调用对象
        error_label: 错误描述标签
        max_retries: 最大重试次数

    Returns:
        成功时返回结果，失败时返回 None
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning(f"⚠ {error_label} 最终失败: {e}")
                return None
            wait = 5.0 * (2 ** attempt)
            logger.debug(f"{error_label} 第{attempt + 1}次失败，{wait:.0f}s后重试")
            await asyncio.sleep(wait)
    return None
