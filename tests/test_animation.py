"""动画控制器测试（M1.5，离线）。"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from PIL import Image
from PySide6.QtGui import QImage

from furina.runtime.animation import AnimationController, AnimationSpec


def _mk_frames(tmp_path: Path, n: int = 2) -> list[str]:
    paths = []
    for i in range(n):
        im = Image.new("RGBA", (32, 48), (255 - i * 60, 120, 200, 255))
        p = tmp_path / f"f{i}.png"
        im.save(p)
        paths.append(str(p))
    return paths


def test_loop_index(tmp_path):
    frames = _mk_frames(tmp_path, 2)
    c = AnimationController(lambda p: QImage(p))
    c.play(AnimationSpec(frames, fps=10, loop=True), now=100.0)
    assert c.frame_count() == 2
    assert c.current_frame_index(now=100.0 + 0.05) == 0
    assert c.current_frame_index(now=100.0 + 0.15) == 1
    assert c.current_frame_index(now=100.0 + 0.25) == 0   # loop 回卷


def test_single_frame_bounds(tmp_path):
    frames = _mk_frames(tmp_path, 2)
    c = AnimationController(lambda p: QImage(p))
    c.play(AnimationSpec(frames, fps=10, loop=False), now=0.0)
    assert c.current_frame_index(now=9.0) == 1   # 非 loop 停在最后一帧
    assert c.current_frame_index(now=99.0) == 1


def test_frame_returns_image(tmp_path):
    frames = _mk_frames(tmp_path, 2)
    c = AnimationController(lambda p: QImage(p))
    c.play(AnimationSpec(frames, fps=10, loop=True))
    img = c.frame(breath=0.0)
    assert img is not None and not img.isNull()


def test_stop(tmp_path):
    frames = _mk_frames(tmp_path, 1)
    c = AnimationController(lambda p: QImage(p))
    c.play(AnimationSpec(frames, fps=10, loop=True))
    assert c.active
    c.stop()
    assert not c.active
    assert c.frame() is None
