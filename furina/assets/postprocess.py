"""素材后处理 —— 抠图（软 alpha + 去边缘染色）（legacy-plan/2 §24）。

Agnes 常返回白底/近白底 JPEG。做法：
1. 四边泛洪找到背景区域。
2. 生成 alpha（背景→0，前景→255），用高斯模糊羽化，得到抗锯齿软边。
3. **un-mix**：对半透明边像素按  alpha 反推前景色（fg = (rgb - bg*(1-a))/a），
   去除白色/背景色污染，避免“白边/黑边/彩边”。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter

from collections import deque


def remove_background_and_crop(path: Path, tolerance: int = 30,
                               feather: float = 1.6, target_h: Optional[int] = None) -> bool:
    """就地处理图片：输出透明背景 PNG（含软边、去染色）。返回是否成功。"""
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return False
    src = np.array(im).astype(np.float32)
    h, w, _ = src.shape

    # 背景色：取四角均值（通常在浅色背景）。
    corners = np.stack([src[0, 0], src[0, w - 1], src[h - 1, 0], src[h - 1, w - 1]])
    bg = corners.mean(axis=0)[:3]

    # ---- 泛洪标记背景连通域（基于与 bg 的距离） ----
    rgb = src[:, :, :3]
    dist = np.linalg.norm(rgb - bg, axis=2)          # (H,W) 到背景色距离
    near = dist <= tolerance
    visited = np.zeros((h, w), dtype=bool)
    q: deque = deque()
    for x in range(w):
        for y in (0, h - 1):
            if near[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if near[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and near[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))

    # ---- alpha：背景 0，前景 255，羽化软边 ----
    alpha = np.where(visited, 0.0, 255.0)
    alpha_img = Image.fromarray(alpha.astype(np.uint8), "L")
    if feather > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(feather))
    alpha_f = np.asarray(alpha_img).astype(np.float32) / 255.0

    # ---- defringe：un-mix 背景色，去除边染 ----
    a = alpha_f
    eps = 1e-3
    # fg = (rgb - bg*(1-a)) / a
    bg_b = bg[None, None, :]
    fg = (rgb - bg_b * (1.0 - a[..., None])) / np.maximum(a[..., None], eps)
    # 完全透明的像素当作背景色即可（对渲染无影响）
    fg = np.clip(fg, 0, 255)

    out = np.concatenate([fg, a[..., None] * 255.0], axis=2).astype(np.uint8)
    out_img = Image.fromarray(out, "RGBA")

    # 裁剪到非透明包围盒
    bbox = out_img.getchannel("A").getbbox()
    if bbox:
        out_img = out_img.crop(bbox)

    if target_h:
        ratio = target_h / out_img.height
        out_img = out_img.resize((int(out_img.width * ratio), target_h), Image.LANCZOS)

    out_img.save(path, "PNG")
    return True
