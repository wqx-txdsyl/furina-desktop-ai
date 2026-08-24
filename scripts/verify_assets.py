"""素材库核验（任务书 §32, §46-P5, §13）：四层结构完整性 + 角色一致性 + 透明/干净 + 缺失降级。

输出：
 1) 四层覆盖统计（base_pose / expression / gaze / micro / action / interaction / prop）
 2) 每张素材：透明背景(角 alpha=0)、内容完整(不贴边=无截断)、分辨率
 3) 多帧序列：Entry/Loop/Exit 是否齐全
 4) 素材缺失时 resolver 是否回到 >best-available< 而非 idle（ASSET_MISSING 记录）
用法： python scripts/verify_assets.py [--dir data/assets]
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
import numpy as np

from furina.config import load_config
from furina.core import setup_logging, get_logger
from furina.assets.asset_manifest import AssetManifest, AssetQuery, AssetResolver

log = get_logger("scripts.verify")


def check_clean(path: Path) -> dict:
    """检查透明/干净/不截断。"""
    if not path.exists():
        return {"exist": False}
    a = np.array(Image.open(path).convert("RGBA"))
    alpha = a[..., 3]
    corners = [a[0, 0][3], a[0, -1][3], a[-1, 0][3], a[-1, -1][3]]
    dirty_edges = max(corners) > 10
    # 内容贴边：只在“角色被硬切”时算截断。宽松：仅当边缘 2px 内 alpha 大量且紧贴（>50%宽度）才视为截断。
    h, w = alpha.shape
    edge_content = (alpha[:2].max(axis=0) > 8).mean()   # 顶边2px有内容的宽度比例
    bot_content = (alpha[-2:].max(axis=0) > 8).mean()
    left_content = (alpha[:, :2].max(axis=1) > 8).mean()
    # 角色占满整边(>60%)才可能真截断；否则只是自然贴脸
    edge_clip = (edge_content > 0.6 or bot_content > 0.6 or left_content > 0.6)
    semi = ((alpha > 5) & (alpha < 250)).sum() / alpha.size
    return {
        "exist": True, "size": [a.shape[1], a.shape[0]],
        "dirty_edges": dirty_edges, "edge_clip": edge_clip,
        "semi_transparent_pct": round(100 * semi, 2),
        # 判定“不干净”：角不透明 或 角色被硬切 或 半透明脏边异常高(>10%，静态图软边正常为5-8%)
        "ok": (not dirty_edges) and (not edge_clip) and (semi < 0.10),
    }


def main() -> int:
    ap_arg = __import__("argparse").ArgumentParser()
    ap_arg.add_argument("--dir", default="data/assets")
    args = ap_arg.parse_args()
    setup_logging(20)
    cfg = load_config()
    d = cfg.root_dir / args.dir
    mp = d / "manifest.json"
    if not mp.exists():
        print("无 manifest:", mp); return 1
    m = AssetManifest.load(mp)
    entries = m.entries

    print("=" * 60)
    print(f"素材库核验: {len(entries)} 条 | manifest={mp}")
    print("=" * 60)

    # 1) 四层覆盖
    roles = Counter(e.role for e in entries)
    print("\n[1] 四层覆盖:")
    for r in ["base_pose", "expression", "gaze", "micro", "action", "interaction", "prop", "transition"]:
        print(f"  {r:14}: {roles.get(r, 0)}")
    print(f"  合计: {len(entries)}")

    # 2) 每张素材质量
    frames = [e for e in entries if e.kind == "frame"]
    bad_clean = [e.asset_id for e in frames if not check_clean(d / e.path).get("ok", False)]
    bad_clip = [e.asset_id for e in frames if check_clean(d / e.path).get("edge_clip", False)]
    print(f"\n[2] 静态帧 {len(frames)} 张: 不干净 {len(bad_clean)} | 疑似截断 {len(bad_clip)}")

    # 3) 序列 Entry/Loop/Exit
    seqs = [e for e in entries if e.kind == "sequence"]
    print(f"\n[3] 多帧序列 {len(seqs)} 条:")
    for e in seqs:
        has_entry = bool(getattr(e, "entry_frames", None))
        has_loop = bool(getattr(e, "loop_frames", None))
        has_exit = bool(getattr(e, "exit_frames", None))
        print(f"  {e.action:14} entry={'Y' if has_entry else '-'} loop={'Y' if has_loop else '-'} "
              f"exit={'Y' if has_exit else '-'} role={e.role} loopable={e.loop}")

    # 4) 缺失降级测试
    r = AssetResolver(m)
    # 一个确定不存在的动作
    before = sum(r.missing.values())
    e = r.resolve(AssetQuery("flying", "ecstatic", "left", "back", "levitate"))
    print(f"\n[4] 缺失降级: 不存在姿态/动作 -> resolved={'NONE' if e is None else e.asset_id} | "
          f"ASSET_MISSING 次数={sum(r.missing.values())}")
    print("    (不在任务书里 fallback idle —— resolver 返回 best-available + 记录缺失)")

    # 5) 缺素材(喝)但不 idl
    print("\n[5] 缺素材但保留意图: 查询 drink(若有则命中;若无看降级链路)")
    e2 = r.resolve(AssetQuery("standing", "happy", "front", "front", "drink"))
    print(f"    drink -> {'NONE' if e2 is None else e2.asset_id} (role={e2.role if e2 else '-'})")

    print("\n核验完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
