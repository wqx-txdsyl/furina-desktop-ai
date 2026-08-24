"""素材质检（plan/2 §24-25）。

四项检查：Identity（是否同一芙宁娜）/ Anatomy（是否崩）/ Style（画风）/ Semantic（是否表达目标语义）。
首版用 PIL 做可自动判定的部分（透明、分辨率、包围盒），语义/身份走 LLM 视觉质检。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image


@dataclass
class QCResult:
    identity: int = 0        # 0..5
    anatomy: int = 0
    style: int = 0
    semantics: int = 0
    transparency: int = 0
    resolution: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.identity + self.anatomy + self.style + self.semantics + self.transparency + self.resolution

    @property
    def verdict(self) -> str:
        # 25 分制（identity 等四项 + transparency + resolution = 30，简化为 5 项*5 归一）
        if self.total >= 22:
            return "production"
        if self.total >= 18:
            return "optional"
        return "regenerate"


class QCEngine:
    def __init__(self, min_size: tuple = (256, 256)) -> None:
        self.min_size = min_size

    def run_automatic(self, path: Path) -> QCResult:
        """自动检查：分辨率 / 透明 / 包围盒。身份与语义留给视觉 QC。"""
        res = QCResult()
        try:
            im = Image.open(path)
            im.load()
        except Exception as e:  # pragma: no cover
            res.notes.append(f"无法打开: {e}")
            return res
        # 分辨率
        w, h = im.size
        if w >= self.min_size[0] and h >= self.min_size[1]:
            res.resolution = 5
        elif w >= 100 and h >= 100:
            res.resolution = 3
        else:
            res.resolution = 1
        # 透明度（RGBA 且存在透明像素）
        if im.mode == "RGBA":
            alpha = im.getchannel("A")
            res.transparency = 5
            res.notes.append(f"RGBA, 包围盒由 alpha 决定")
        elif im.mode in ("RGB", "P"):
            res.transparency = 2
            res.notes.append("无 alpha 通道，需背景移除")
        return res

    def run_with_vision(self, path: Path, target_semantics: dict, describe_fn) -> QCResult:
        """用 LLM 视觉做身份/语义质检。describe_fn(image_path, prompt)->str。"""
        res = self.run_automatic(path)
        if describe_fn:
            id_text = describe_fn(str(path), "This character's identity: single color hair, blue hat, chibi Genshin Furina. Rate identity 0-5.")
            sem_text = describe_fn(str(path), f"Does this image show [{target_semantics}]? Rate semantics 0-5, answer with number only.")
            res.identity = _clamp_num(id_text, 2)
            res.semantics = _clamp_num(sem_text, 2)
        return res


def _clamp_num(text: str, default: int) -> int:
    import re
    m = re.search(r"\d", text)
    if m:
        return max(0, min(5, int(m.group())))
    return default
