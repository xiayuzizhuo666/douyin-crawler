from typing import Tuple, Dict, Any, List, Optional, TYPE_CHECKING

from crawler.detail import has_shopping_cart, confirm_shopping_cart
from analyzer.time_parser import format_timestamp
from utils.logger import logger

if TYPE_CHECKING:
    from crawler.engine import DouyinEngine


class InfluencerAnalyzer:
    """带货达人判定引擎

    遍历达人作品列表 → 区分视频/图文 → 检测挂车 → 判定是否为 "视频带货达人"
    """

    async def analyze(
        self,
        author: dict,
        aweme_list: List[dict],
        engine: Optional["DouyinEngine"] = None,
        skip_detail: bool = False,
    ) -> Dict[str, Any]:
        """分析一个达人的作品列表，判定是否为视频带货达人

        Args:
            author: 达人基本信息 {"sec_uid": ..., "nickname": ..., "uid": ...}
            aweme_list: 达人作品列表（来自 /aweme/v1/web/aweme/post/）
            engine: DouyinEngine 实例，提供后可启用挂车检测 fallback
            skip_detail: True=只检查主页列表数据不调详情接口（极速模式，省时间但可能漏判）

        Returns:
            {
                "qualified": True/False,
                "data": {
                    "homepage_url": "达人主页链接",
                    "nickname": "达人昵称",
                    "shopping_video_url": "最近挂车作品链接",
                    "last_video_time": "最后一条视频发布时间",
                    "shopping_video_count": 挂车视频数量,
                    "total_video_count": 视频总数,
                }
            }
        """
        sec_uid = author.get("sec_uid", "")
        nickname = author.get("nickname", "未知")
        homepage_url = f"https://www.douyin.com/user/{sec_uid}"

        video_posts = []
        shopping_video_posts = []
        image_posts = 0

        for aweme in aweme_list:
            aweme_type = aweme.get("aweme_type", -1)

            if aweme_type == 68:
                image_posts += 1
                continue

            # 视频类型: 0=普通视频, 55=长视频/直播回放, 还有其他视频子类型
            if aweme_type in (0, 55, 51, 61, 77, 101, 107):
                video_posts.append(aweme)
                if skip_detail or engine is None:
                    has_cart = has_shopping_cart(aweme)
                else:
                    has_cart = await confirm_shopping_cart(engine, aweme)
                if has_cart:
                    shopping_video_posts.append(aweme)

        logger.debug(
            f"  {nickname}: 视频={len(video_posts)}, "
            f"挂车视频={len(shopping_video_posts)}, "
            f"图文={image_posts}"
        )

        if not shopping_video_posts:
            return {"qualified": False, "data": {}}

        latest_shopping = max(shopping_video_posts, key=lambda x: x.get("create_time", 0))
        latest_video = max(video_posts, key=lambda x: x.get("create_time", 0))

        shopping_aweme_id = latest_shopping.get("aweme_id", "")
        shopping_video_url = (
            f"https://www.douyin.com/video/{shopping_aweme_id}"
            if shopping_aweme_id else ""
        )
        last_video_time = format_timestamp(latest_video.get("create_time", 0))

        return {
            "qualified": True,
            "data": {
                "homepage_url": homepage_url,
                "nickname": nickname,
                "shopping_video_url": shopping_video_url,
                "last_video_time": last_video_time,
                "shopping_video_count": len(shopping_video_posts),
                "total_video_count": len(video_posts),
            },
        }
