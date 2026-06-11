import json

from crawler.engine import DouyinEngine
from utils.logger import logger

ENABLE_ANCHOR_DEBUG = False


async def crawl_post_detail(
    engine: DouyinEngine,
    aweme_id: str,
) -> dict:
    """获取单个作品详情（挂车检测 fallback）

    当主页作品列表中的 anchor_info 为空或不完整时，
    通过作品详情接口获取完整数据以确认挂车状态。

    Args:
        engine: DouyinEngine 实例
        aweme_id: 作品 ID

    Returns:
        dict: 作品详情数据 (aweme_detail)，或 None
    """
    api = "/aweme/v1/web/aweme/detail/"

    params = {
        "aweme_id": aweme_id,
        "version_code": "190500",
        "version_name": "19.5.0",
    }

    video_url = f"https://www.douyin.com/video/{aweme_id}"
    resp = await engine.get(api, params=params, referer=video_url)

    aweme_detail = resp.get("aweme_detail")
    if aweme_detail:
        return aweme_detail

    logger.debug(f"  aweme_id={aweme_id} 详情接口未返回数据")
    return None


async def confirm_shopping_cart(engine: DouyinEngine, aweme: dict) -> bool:
    """确认作品是否挂车（优先用列表数据，失败则调用详情接口）

    Args:
        engine: DouyinEngine 实例
        aweme: 作品数据（来自用户主页列表或搜索结果）

    Returns:
        bool: 是否挂车
    """
    if has_shopping_cart(aweme):
        return True

    aweme_id = aweme.get("aweme_id")
    if not aweme_id:
        return False

    detail = await crawl_post_detail(engine, str(aweme_id))
    if detail:
        return has_shopping_cart(detail)

    return False


def has_shopping_cart(aweme: dict) -> bool:
    """检测作品是否带有商品链接（小黄车/橱窗）

    判断依据（按优先级）：
    1. anchor_info 字段存在且有效 → 有挂车
    2. anchors 字段存在且非空列表 → 有挂车
    3. interaction_stickers 中包含购物车贴纸 → 有挂车
    """
    if ENABLE_ANCHOR_DEBUG:
        logger.debug(f"aweme_id={aweme.get('aweme_id')} aweme_type={aweme.get('aweme_type')}")
        ai_raw = aweme.get("anchor_info")
        logger.debug(f"anchor_info={json.dumps(ai_raw, ensure_ascii=False, indent=2) if ai_raw else None}")
        logger.debug(f"anchors={json.dumps(aweme.get('anchors'), ensure_ascii=False)}")
        stickers_raw = aweme.get("interaction_stickers")
        logger.debug(f"interaction_stickers={json.dumps(stickers_raw, ensure_ascii=False)}")

    anchor_info = aweme.get("anchor_info")
    if anchor_info and isinstance(anchor_info, dict):
        anchor_type = anchor_info.get("type")
        if anchor_type is not None:
            return True
        extra = anchor_info.get("extra")
        if extra and isinstance(extra, str) and len(extra) > 0:
            return True
        if anchor_info.get("anchor_id") or anchor_info.get("icon"):
            return True

    anchors = aweme.get("anchors")
    if anchors and isinstance(anchors, list) and len(anchors) > 0:
        return True

    stickers = aweme.get("interaction_stickers")
    if stickers:
        for s in stickers:
            s_type = str(s.get("type", "")).lower()
            if "commerce" in s_type:
                return True
            if s.get("commerce_info"):
                return True

    return False
