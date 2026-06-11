from datetime import datetime, timezone, timedelta

TZ_UTC8 = timezone(timedelta(hours=8))


def format_timestamp(ts: int, tz: timezone = TZ_UTC8) -> str:
    """将 Unix 时间戳（秒）转为 YYYY-MM-DD 格式

    参考: DouYin_Spider data_util.py L21-L24 timestamp_to_str

    Args:
        ts: Unix 时间戳（秒）
        tz: 时区，默认 UTC+8（北京时间）

    Returns:
        str: YYYY-MM-DD 格式日期，异常时返回 "未知"
    """
    if not ts or ts <= 0:
        return "未知"
    try:
        return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "未知"
