"""抖音话题下「视频带货达人」信息采集脚本

用法:
    python main.py --keyword "#防晒好物"
    python main.py                      # 交互式输入
    python main.py -k "防晒" -n 20 -o ./my_output
    python main.py --gui                # 启动桌面 GUI
"""

import argparse
import asyncio
import sys
import os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.engine import DouyinEngine
from crawler.search import crawl_search_results, extract_unique_authors
from crawler.user import crawl_user_posts
from analyzer.filter import InfluencerAnalyzer
from storage.excel import save_to_xlsx
from utils.logger import logger
from utils.retry import RateLimiter
from config import (
    SCAN_POST_COUNT,
    SEARCH_SORT_TYPE,
    SEARCH_PUBLISH_TIME,
    SEARCH_MAX_COUNT,
    OUTPUT_DIR,
    MIN_FOLLOWER_COUNT,
    load_cookie,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="抖音话题下视频带货达人信息采集",
    )
    parser.add_argument(
        "--keyword", "-k", type=str, default=None,
        help="话题关键词，如 '#防晒好物'",
    )
    parser.add_argument(
        "--count", "-n", type=int, default=SCAN_POST_COUNT,
        help=f"每个达人扫描作品数，默认 {SCAN_POST_COUNT}",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=OUTPUT_DIR,
        help=f"输出目录，默认 {OUTPUT_DIR}",
    )
    parser.add_argument(
        "--cookie", "-c", type=str, default=None,
        help="Cookie 字符串（不提供则从 .env 读取）",
    )
    parser.add_argument(
        "--sort", "-s", type=int, default=SEARCH_SORT_TYPE,
        choices=[0, 1, 2],
        help=f"排序方式 0=综合 1=最多点赞 2=最新发布，默认 {SEARCH_SORT_TYPE}",
    )
    parser.add_argument(
        "--time", "-t", type=int, default=SEARCH_PUBLISH_TIME,
        help=f"发布时间过滤 0=不限 7=一周 180=半年，默认 {SEARCH_PUBLISH_TIME}",
    )
    parser.add_argument(
        "--max-search", type=int, default=SEARCH_MAX_COUNT,
        help=f"搜索结果上限，默认 {SEARCH_MAX_COUNT}",
    )
    parser.add_argument(
        "--min-followers", type=int, default=MIN_FOLLOWER_COUNT,
        help=f"最低粉丝数过滤（0=不过滤），默认 {MIN_FOLLOWER_COUNT}",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="禁用彩色日志输出",
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="启动桌面 GUI 界面",
    )
    return parser.parse_args()


async def run_pipeline(
    keyword: str,
    scan_count: int = SCAN_POST_COUNT,
    sort_type: int = SEARCH_SORT_TYPE,
    publish_time: int = SEARCH_PUBLISH_TIME,
    max_search: int = SEARCH_MAX_COUNT,
    min_followers: int = MIN_FOLLOWER_COUNT,
    output_dir: str = OUTPUT_DIR,
    cookie_str: str = None,
):
    """主采集流水线

    Step 1: 搜索话题 → 获取视频列表
    Step 2: 提取视频作者 → 去重 → 潜在达人列表
    Step 3: 遍历达人主页 → 扫描 N 条作品 → 判断是否视频带货
    Step 4: 保留合格达人 → 导出 Excel
    """
    logger.info("=" * 55)
    logger.info("  抖音话题下「视频带货达人」信息采集")
    logger.info("=" * 55)

    try:
        cookie_info = load_cookie()
    except ValueError as e:
        logger.error(f"Cookie 加载失败: {e}")
        return None
    if cookie_str:
        cookie_info["cookie_str"] = cookie_str

    mgr = None
    cookie_provider = None
    try:
        from utils.browser_manager import BrowserCookieManager
        mgr = BrowserCookieManager()
        await mgr.start()
        if mgr.is_logged_in:
            cookie_provider = mgr.make_cookie_provider()
            logger.info("✓ 使用浏览器 Provider 模式 (动态 Cookie)")
    except Exception:
        if mgr:
            try:
                await mgr.stop()
            except Exception:
                pass

    engine = DouyinEngine(
        cookie_str=cookie_info["cookie_str"] if not cookie_provider else None,
        cookie_provider=cookie_provider,
    )
    analyzer = InfluencerAnalyzer()
    rate_limiter = RateLimiter()
    from config import SPEED_PROFILES, DEFAULT_SPEED_MODE
    rate_limiter.apply_profile(SPEED_PROFILES[DEFAULT_SPEED_MODE])

    try:
        valid = await engine.check_cookie_valid()
        if not valid:
            logger.warning("Cookie 可能已过期，继续尝试...")

        logger.info(f"")
        logger.info(f"Step 1/4: 搜索话题 '{keyword}' ...")
        logger.info(f"  排序={sort_type} 时间范围={publish_time} 上限={max_search}")

        all_videos = await crawl_search_results(
            engine, keyword,
            sort_type=sort_type,
            publish_time=publish_time,
            max_count=max_search,
            limiter=rate_limiter,
        )
        if not all_videos:
            logger.error(f"未搜索到 '{keyword}' 相关视频，请检查关键词或 Cookie")
            return None
        logger.info(f"  ✓ 共获取 {len(all_videos)} 条视频")

        logger.info(f"")
        logger.info(f"Step 2/4: 提取唯一作者 ...")
        unique_authors = extract_unique_authors(all_videos, min_followers=min_followers)
        logger.info(f"  → 去重后 {len(unique_authors)} 位潜在达人")

        if min_followers > 0:
            logger.info(f"  → 粉丝数过滤: ≥ {min_followers}")

        if not unique_authors:
            logger.warning("未提取到任何作者")
            return None

        logger.info(f"")
        logger.info(f"Step 3/4: 扫描达人主页 (最多 {scan_count} 条作品/人)...")

        qualified_data = []
        total = len(unique_authors)

        for i, author in enumerate(unique_authors, 1):
            sec_uid = author["sec_uid"]
            nickname = author["nickname"]
            prefix = f"  [{i}/{total}]"

            await rate_limiter.wait("user")
            engine.rotate_ua()

            try:
                posts = await crawl_user_posts(engine, sec_uid, max_count=scan_count, limiter=rate_limiter)
                if not posts:
                    logger.info(f"{prefix} ✗ {nickname} (无作品)")
                    continue

                result = await analyzer.analyze(author, posts, engine=engine)
                if result["qualified"]:
                    data = result["data"]
                    qualified_data.append(data)
                    logger.info(
                        f"{prefix} ✓ {nickname} "
                        f"| 视频{data['total_video_count']}条 "
                        f"挂车{data['shopping_video_count']}条"
                    )
                else:
                    logger.info(f"{prefix} ✗ {nickname} (非视频带货)")

            except Exception as e:
                logger.warning(f"{prefix} ⚠ {nickname} 失败: {e}")
                continue

        logger.info(f"")
        logger.info(f"Step 4/4: 导出结果 ...")
        logger.info(f"  → 视频带货达人: {len(qualified_data)} 位")

        if not qualified_data:
            logger.warning("未找到符合条件的视频带货达人")
            filepath = save_to_xlsx([], keyword, output_dir)
            logger.info(f"✅ 已生成空表: {filepath}")
            return filepath

        filepath = save_to_xlsx(qualified_data, keyword, output_dir)
        logger.info(f"")
        logger.info(f"✅ 完成！文件已保存至: {filepath}")
        logger.info(f"   共 {len(qualified_data)} 位视频带货达人")

        return filepath

    finally:
        await engine.close()
        if mgr:
            try:
                await mgr.stop()
            except Exception:
                pass


def main():
    args = parse_args()

    if args.gui:
        from gui_app import main as gui_main
        gui_main()
        return

    keyword = args.keyword
    if not keyword:
        try:
            keyword = input("请输入话题关键词: ").strip()
        except (EOFError, RuntimeError, OSError):
            from gui_app import main as gui_main
            gui_main()
            return
        if not keyword:
            sys.exit(1)

    asyncio.run(
        run_pipeline(
            keyword=keyword,
            scan_count=args.count,
            sort_type=args.sort,
            publish_time=args.time,
            max_search=args.max_search,
            min_followers=args.min_followers,
            output_dir=args.output,
            cookie_str=args.cookie,
        )
    )


if __name__ == "__main__":
    main()
