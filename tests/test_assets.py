"""素材引擎测试（M1）。"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from furina.assets.asset_manifest import (
    AssetEntry,
    AssetManifest,
    AssetQuery,
    AssetResolver,
    naming_for,
    semantic_id_for,
)
from furina.assets.agnes_client import _as_data_uris
from furina.assets.postprocess import remove_background_and_crop
from furina.assets.qc import QCEngine


def test_naming_and_semantic():
    assert naming_for("sitting", "happy", "user", "idle", 2) == "furina_sitting_happy_user_idle_02"
    assert semantic_id_for("sitting", "happy", "user", "front", "idle") == "sitting/happy/user/front/idle"


def test_manifest_roundtrip(tmp_path):
    m = AssetManifest(character="furina", version="v1")
    m.entries.append(AssetEntry(asset_id="a1", posture="sitting", emotion="happy",
                                gaze="user", action="idle", anchors={"head": [0.5, 0.2]}))
    p = tmp_path / "m.json"
    m.save(p)
    m2 = AssetManifest.load(p)
    assert m2.entries[0].asset_id == "a1"
    assert m2.entries[0].anchors["head"] == [0.5, 0.2]


def test_manifest_index():
    m = AssetManifest(entries=[AssetEntry(asset_id="a1"), AssetEntry(asset_id="a2")])
    idx = m.index()
    assert set(idx) == {"a1", "a2"}


def test_resolver_exact_and_fallback():
    m = AssetManifest(entries=[
        AssetEntry(asset_id="a1", posture="sitting", emotion="happy", gaze="user", action="idle"),
        AssetEntry(asset_id="a2", posture="sitting", emotion="neutral", gaze="front", action="idle"),
        AssetEntry(asset_id="a3", posture="standing", emotion="neutral", gaze="front", action="idle"),
    ])
    r = AssetResolver(m)
    assert r.resolve(AssetQuery("sitting", "happy", "user", "front", "idle")).asset_id == "a1"
    # 无躺姿 → 回退到 same posture? 没有 lying，则 same emotion? 没有 → neutral standing
    e = r.resolve(AssetQuery("lying", "angry", "user", "front", "eat"))
    assert e.posture == "standing" and e.emotion == "neutral"


def test_data_uri_local():
    out = _as_data_uris([__file__])
    assert out[0].startswith("data:image/png;base64,")
    b64 = out[0].split(",", 1)[1]
    assert len(base64.b64decode(b64)) > 0


def test_qc_automatic_transparency(tmp_path):
    # 画一个 300x300 白底 + 中间矩形（RGBA 不透明）
    im = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([100, 100, 200, 200], fill=(0, 0, 255, 255))
    p = tmp_path / "x.png"
    im.save(p)
    res = QCEngine().run_automatic(p)
    assert res.resolution == 5
    assert res.transparency == 5 or res.transparency == 2


def test_remove_background_crop(tmp_path):
    # 白底 + 蓝矩形
    im = Image.new("RGBA", (400, 500), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([150, 200, 250, 300], fill=(0, 0, 255, 255))
    p = tmp_path / "b.png"
    im.save(p)
    assert remove_background_and_crop(p) is True
    out = Image.open(p)
    assert out.mode == "RGBA"
    # 裁剪后应显著小于 400x500（去掉了大块白边）
    assert out.width < 400 and out.height < 500
    # 中心区域应为不透明（角色保留）
    cx, cy = out.width // 2, out.height // 2
    assert out.getpixel((cx, cy))[3] > 0


def test_remove_background_soft_edge(tmp_path):
    """关键：抠图应产出软/抗锯齿 alpha（半透明边），而非二值硬边（避免黑边）。"""
    import numpy as np
    im = Image.new("RGBA", (400, 500), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([150, 200, 250, 300], fill=(0, 0, 255, 255))
    p = tmp_path / "soft.png"
    im.save(p)
    assert remove_background_and_crop(p, feather=1.8) is True
    a = np.array(Image.open(p).convert("RGBA"))
    alpha = a[:, :, 3]
    soft = int(((alpha > 10) & (alpha < 245)).sum())
    assert soft > 0, "应存在半透明软边像素"
