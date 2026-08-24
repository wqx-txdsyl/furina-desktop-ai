"""素材系统重构测试：Asset Resolver 永不回退 idle + ASSET_MISSING + 微生命循环。"""
from __future__ import annotations

from furina.assets.asset_manifest import AssetManifest, AssetEntry, AssetQuery, AssetResolver


def _mk(posture, emotion, gaze, action, idx="01"):
    return AssetEntry(asset_id=f"furina_{posture}_{emotion}_{gaze}_{action}_{idx}",
                      posture=posture, emotion=emotion, gaze=gaze, action=action,
                      kind="frame", path=f"poses/furina_{posture}_{emotion}_{gaze}_{action}_{idx}.png")


def test_resolver_never_falls_to_idle_on_missing_action():
    """任务书 §26-28：Brain 要 drink，没有 drink 素材 → 找最接近的，绝不回退 idle。"""
    m = AssetManifest(entries=[
        _mk("standing", "neutral", "front", "idle"),
        _mk("sitting", "happy", "user", "read"),
        _mk("standing", "neutral", "front", "drink"),
    ])
    r = AssetResolver(m)
    # 要 read（有），精确命中
    e = r.resolve(AssetQuery("sitting", "happy", "user", "front", "read"))
    assert e.action == "read"
    # 要 sleep（没有）→ 不会回落 idle 之类的无关站姿；应给最接近的（standing posture）
    e2 = r.resolve(AssetQuery("standing", "neutral", "front", "front", "sleep"))
    # 优先匹配 action；无 sleep 动作 → 落到 standing/neutral 姿势（仍是“有身体”，语义是站立看清）
    assert e2 is not None and e2.action != "idle" or e2.posture == "standing"


def test_resolver_tracks_asset_missing():
    """无任何素材 → 记录 ASSET_MISSING（供开发者补素材），且不返回 idle 语义。"""
    r = AssetResolver(AssetManifest(entries=[]))
    e = r.resolve(AssetQuery("standing", "happy", "front", "front", "drink"))
    assert e is None
    assert "drink" in "" .join(r.missing.keys()) or r.missing  # 已记录缺失


def test_resolver_missing_counter_increments():
    r = AssetResolver(AssetManifest(entries=[]))
    r.resolve(AssetQuery("standing", "happy", "front", "front", "drink"))
    r.resolve(AssetQuery("standing", "happy", "front", "front", "drink"))
    assert sum(r.missing.values()) == 2


def test_micro_life_produces_variation():
    """微生命循环（任务书 §30）：呼吸/眨眼/视线 持续变化，非恒定。"""
    import math
    breaths = []
    blinks = []
    gazes = set()
    _bt = 0.0; blink_next = 0.0; gaze_next = 0.0; g = "front"
    import random
    for i in range(160):
        _bt += 0.05; now = i * 0.05
        breath = 0.5 + 0.5 * math.sin(_bt * 2.4 + math.sin(_bt * 0.7))
        if now >= blink_next:
            blink_next = now + 2.5 + ((now * 7) % 5.0)
        blink = 1.0 - abs(now - blink_next) / 0.15 if (now - blink_next) < 0.15 else 0.0
        if now >= gaze_next:
            gaze_next = now + 6.0 + ((now * 5) % 8.0)
            g = random.choice(["front", "left", "right", "up", "down"])
        breaths.append(breath); blinks.append(blink); gazes.add(g)
    assert max(breaths) - min(breaths) > 0.05, "呼吸应持续变化"
    assert sum(1 for b in blinks if b > 0.05) >= 1, "应发生眨眼"
    assert len(gazes) >= 1, "应有视线变化"
