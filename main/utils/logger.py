import sys
from pathlib import Path
from loguru import logger

logger.remove()
if sys.stdout is not None:
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

_log_dir = Path("logs")
try:
    _log_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

logger.add(
    str(_log_dir / "douyin_{time:YYYY-MM-DD}.log"),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
)

__all__ = ["logger"]
