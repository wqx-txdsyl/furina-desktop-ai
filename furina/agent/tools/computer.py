"""屏幕/计算机观察工具（legacy-plan/5 §6-7, §10 —— 给 Agent 一双“眼睛”）。

用 PIL ImageGrab 抓取前台屏幕，返回：截图路径 + 尺寸 + 可选的视觉描述。
视觉描述需要 LLM（vision），由上层整合；本工具只负责抓图并产出可被 vision 消费的路径。

骨架原则：结构化、可验证；不越权（只读）、失败如实返回。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..permission import Permission
from ..tool import BaseTool, ToolResult


class ScreenshotTool(BaseTool):
    name = "computer.screenshot"
    description = "抓取当前屏幕截图（只读），返回截图文件路径与尺寸，供后续视觉观察"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"save_path": {"type": "string"}}}

    def run(self, save_path: Optional[str] = None) -> ToolResult:
        try:
            from PIL import ImageGrab
        except Exception as e:  # pragma: no cover - 无 GUI/非桌面环境
            return ToolResult(False, error=f"无法使用 ImageGrab: {e}", verified=False)
        try:
            img = ImageGrab.grab(all_screens=False)
        except Exception as e:  # pragma: no cover
            return ToolResult(False, error=f"截屏失败: {e}", verified=False)
        if save_path:
            p = Path(save_path)
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, sp = tempfile.mkstemp(suffix=".png", prefix="furina_screen_")
            import os
            os.close(fd)
            p = Path(sp)
        img.save(p, "PNG")
        return ToolResult(True,
                          data={"path": str(p), "w": img.width, "h": img.height},
                          verified=bool(p.exists() and p.stat().st_size > 0),
                          note=f"截图已保存 {p} ({img.width}x{img.height})")
