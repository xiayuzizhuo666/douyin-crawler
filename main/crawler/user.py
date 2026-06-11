from crawler.engine import DouyinEngine
from utils.logger import logger
from utils.retry import retry_on_failure, RateLimiter
import config


@retry_on_failure(max_retries=3, base_delay=5.0)
async def _user_post_page(engine, api, params, referer):
    """获取用户作品单页（带重试）"""
    return await engine.get(api, params=params, referer=referer)


async def crawl_user_posts(
    engine: DouyinEngine,
    sec_user_id: str,
    max_count: int = None,
    limiter: RateLimiter = None,
) -> list:
    """采集达人主页作品列表（带分页）

    Args:
        engine: DouyinEngine 实例
        sec_user_id: 用户 sec_uid
        max_count: 最多采集作品数
        limiter: 共享的 RateLimiter 实例（并发场景必须传入，否则内部创建）

    Returns:
        list[dict]: 作品列表（aweme_list 中的每一项）
    """
    if limiter is None:
        limiter = RateLimiter()
    if max_count is None:
        max_count = config.SCAN_POST_COUNT
    api = "/aweme/v1/web/aweme/post/"
    max_cursor = "0"
    all_posts = []

    while len(all_posts) < max_count:
        params = {
            "sec_user_id": sec_user_id,
            "max_cursor": max_cursor,
            "locate_query": "false",
            "show_live_replay_strategy": "1",
            "need_time_list": "1" if max_cursor == "0" else "0",
            "time_list_query": "0",
            "whale_cut_token": "",
            "cut_version": "1",
            "count": "18",
            "publish_video_strategy_type": "2",
        }

        user_url = f"https://www.douyin.com/user/{sec_user_id}"

        await limiter.wait("post")

        resp = await _user_post_page(engine, api, params, user_url)

        sc = resp.get("status_code", 0)
        if sc == 2483:
            logger.warning(f"需要登录，Cookie 已过期")
            break
        if sc != 0:
            msg = resp.get("status_msg", "未知错误")
            logger.warning(f"用户作品接口返回错误: code={sc}, msg={msg}")
            break

        aweme_list = resp.get("aweme_list")
        if not aweme_list:
            logger.debug(f"  sec_uid={sec_user_id[:20]} 无作品或获取失败")
            break

        all_posts.extend(aweme_list)

        has_more = resp.get("has_more", 0)
        if has_more != 1:
            break
        max_cursor = str(resp.get("max_cursor", "0"))
        if max_cursor == "0":
            break

    if len(all_posts) > max_count:
        all_posts = all_posts[:max_count]

    return all_posts
