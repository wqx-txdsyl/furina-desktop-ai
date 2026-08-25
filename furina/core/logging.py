"""日志：统一 stdlib logging，便于决策轨迹追踪（legacy-plan/8 铁律#15）。"""
from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根 logger；FURINA_DEBUG=1 时输出 DEBUG。"""
    root = logging.getLogger("furina")
    if root.handlers:
        return
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"furina.{name}")
