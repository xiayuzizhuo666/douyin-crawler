from urllib.parse import quote

from crawler.engine import DouyinEngine
from utils.logger import logger
from utils.retry import retry_on_failure, RateLimiter
import config


@retry_on_failure(max_retries=3, base_delay=5.0)
async def _search_page(engine, api, params, referer):
    """搜索单页（带重试）"""
    return await engine.get(api, params=params, referer=referer)


async def crawl_search_results(
    engine: DouyinEngine,
    keyword: str,
    sort_type: int = None,
    publish_time: int = None,
    max_count: int = None,
    limiter: RateLimiter = None,
) -> list:
    """搜索话题下的视频列表（带分页）

    Args:
        engine: DouyinEngine 实例
        keyword: 搜索关键词，如 '#防晒好物'
        sort_type: 排序 0=综合 1=最多点赞 2=最新发布
        publish_time: 发布时间 0=不限 7=一周 180=半年
        max_count: 最大搜索数量
        limiter: 共享的 RateLimiter 实例（并发场景必须传入，否则内部创建）

    Returns:
        list[dict]: 视频列表，每项为搜索结果 item
    """
    if limiter is None:
        limiter = RateLimiter()
    if sort_type is None:
        sort_type = config.SEARCH_SORT_TYPE
    if publish_time is None:
        publish_time = config.SEARCH_PUBLISH_TIME
    if max_count is None:
        max_count = config.SEARCH_MAX_COUNT

    api = "/aweme/v1/web/general/search/single/"
    offset = 0
    all_items = []
    search_id = None

    while len(all_items) < max_count:
        params = {
            "search_channel": "aweme_general",
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "offset": str(offset),
            "count": "25",
            "need_filter_settings": "0",
            "list_type": "single",
            "version_code": "190600",
            "version_name": "19.6.0",
        }

        if search_id:
            params["search_id"] = search_id

        if sort_type != 0:
            params["sort_type"] = str(sort_type)
        if publish_time != 0:
            params["publish_time"] = str(publish_time)

        referer = f"https://www.douyin.com/search/{quote(keyword)}?type=general"

        await limiter.wait("search")

        resp = await _search_page(engine, api, params, referer)

        sc = resp.get("status_code", 0)
        if sc == 2483:
            logger.warning("需要登录，请更新 Cookie")
            break
        if sc != 0:
            msg = resp.get("status_msg", "未知错误")
            logger.warning(f"搜索接口返回错误: code={sc}, msg={msg}")
            break

        data = resp.get("data")
        if not data or not isinstance(data, list):
            logger.warning("搜索结果为空或格式异常")
            break

        all_items.extend(data)
        logger.info(f"  搜索进度: {len(all_items)} 条视频")

        has_more = resp.get("has_more", 0)
        if has_more != 1:
            break

        cursor = resp.get("cursor", 0)
        offset = int(cursor)

        log_pb = resp.get("log_pb") or resp.get("extra", {})
        search_id = log_pb.get("impr_id", search_id)

    if len(all_items) > max_count:
        all_items = all_items[:max_count]

    return all_items


async def crawl_search_multi(
    engine_factory,
    keyword: str,
    sort_types: list = None,
    publish_time: int = None,
    max_per_round: int = None,
    limiter: RateLimiter = None,
) -> list:
    """多轮搜索：用不同排序方式分别搜索后合并去重

    突破单次搜索 ~500 条的上限。用不同排序方式各搜一轮，
    按 aweme_id 去重合并，能搜集到更多不同的达人和视频。

    Args:
        engine_factory: callable() -> DouyinEngine，每轮创建新引擎
        keyword: 搜索关键词
        sort_types: 排序方式列表，默认 [1, 2]（最多点赞+最新发布）
        publish_time: 发布时间过滤
        max_per_round: 每轮最大条数，None 用 config 默认值
        limiter: 共享的 RateLimiter

    Returns:
        list[dict]: 合并去重后的搜索结果
    """
    if sort_types is None:
        sort_types = config.MULTI_ROUND_SORT_TYPES
    if max_per_round is None:
        max_per_round = config.SEARCH_MAX_COUNT

    all_items = []
    seen_ids = set()

    for st in sort_types:
        engine = engine_factory()
        try:
            logger.info(f"  多轮搜索: sort_type={st} ...")
            items = await crawl_search_results(
                engine, keyword,
                sort_type=st,
                publish_time=publish_time,
                max_count=max_per_round,
                limiter=limiter,
            )
            new_count = 0
            for item in items:
                aweme_info = _safe_get_aweme_info(item)
                aweme_id = aweme_info.get("aweme_id", "") if aweme_info else ""
                if aweme_id and aweme_id not in seen_ids:
                    seen_ids.add(aweme_id)
                    all_items.append(item)
                    new_count += 1
                elif not aweme_id:
                    all_items.append(item)
                    new_count += 1
            logger.info(f"    sort_type={st}: {len(items)} 条 → 新增 {new_count} 条")
        finally:
            await engine.close()

    logger.info(f"  多轮搜索完成: 共 {len(all_items)} 条 (去重后)")
    return all_items


def _safe_get_aweme_info(item: dict) -> dict:
    """安全提取 aweme_info，防止空 mix_items 导致 IndexError"""
    aweme_info = item.get("aweme_info")
    if aweme_info:
        return aweme_info
    mix_items = item.get("aweme_mix_info", {}).get("mix_items") or []
    return mix_items[0] if mix_items else {}


def extract_unique_authors(video_list: list, min_followers: int = 0) -> list:
    """从搜索结果中提取去重后的作者列表

    Args:
        video_list: 搜索结果列表
        min_followers: 最低粉丝数过滤（0=不过滤）

    Returns:
        list[dict]: 去重后作者列表 [{"sec_uid": ..., "nickname": ..., "uid": ...}, ...]
    """
    seen = set()
    authors = []
    for item in video_list:
        aweme_info = _safe_get_aweme_info(item)
        if not aweme_info:
            continue
        author = aweme_info.get("author", {})
        sec_uid = author.get("sec_uid") or author.get("sec_uid_str", "")
        if sec_uid and sec_uid not in seen:
            fc = author.get("follower_count", 0)
            if min_followers > 0 and fc < min_followers:
                logger.debug(f"  低粉过滤: {author.get('nickname', '?')} 粉丝={fc} < {min_followers}")
                continue
            seen.add(sec_uid)
            authors.append({
                "sec_uid": sec_uid,
                "nickname": author.get("nickname", "未知"),
                "uid": author.get("uid", ""),
                "follower_count": author.get("follower_count", 0),
            })
    return authors
