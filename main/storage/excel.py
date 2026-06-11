import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import openpyxl

from config import OUTPUT_DIR
from utils.logger import logger


ILLEGAL_CHARACTERS_RE = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')


def norm_text(text: str) -> str:
    """清理非法字符（参考 DouYin_Spider data_util.py L16-L18）"""
    return ILLEGAL_CHARACTERS_RE.sub('', text)


def save_to_xlsx(
    data_list: List[Dict[str, str]],
    keyword: str,
    output_dir: str = OUTPUT_DIR,
) -> str:
    """将带货达人数据保存为 Excel 文件（四列结构）

    参考: DouYin_Spider data_util.py L112-L121

    Args:
        data_list: 达人数据列表，每项含:
            - homepage_url:     达人主页链接
            - nickname:         达人昵称
            - shopping_video_url: 最近挂车作品链接
            - last_video_time:  最后一条视频发布时间
        keyword: 搜索关键词，用于文件名
        output_dir: 输出目录

    Returns:
        str: 生成的文件路径
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "视频带货达人"

    ws.append([
        "达人主页链接",
        "达人昵称",
        "最近挂车作品链接",
        "最后一条视频发布时间",
    ])

    if not data_list:
        ws.append(["（本次采集未找到符合条件的视频带货达人）", "", "", ""])

    for item in data_list:
        ws.append([
            norm_text(str(item.get("homepage_url", ""))),
            norm_text(str(item.get("nickname", ""))),
            norm_text(str(item.get("shopping_video_url", ""))),
            norm_text(str(item.get("last_video_time", ""))),
        ])

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 50
    ws.column_dimensions['D'].width = 22

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    safe_keyword = re.sub(r'[\\/:*?"<>|#]+', '', keyword).strip()
    if not safe_keyword:
        safe_keyword = "data"

    filename = f"{safe_keyword}_视频带货达人_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = output_path / filename
    wb.save(str(filepath))

    logger.info(f"数据已保存至 {filepath}")
    return str(filepath)
