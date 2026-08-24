"""资产批量生成脚本（M1）。

基于 furina-base.png 用 Agnes (agnes-image-2.1-flash) 做图生图，
生成一组姿态/表情/视线/微动作素材，跑 QC，写 manifest.json 到 data/assets/。

用法：
    python scripts/generate_assets.py --dry-run            # 只看要生成什么
    python scripts/generate_assets.py                      # 真实生成（当前 $0）
    python scripts/generate_assets.py --only sit_happy     # 只生成指定语义
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.config import load_config
from furina.assets.agnes_client import AgnesClient
from furina.assets.pipeline import AssetPipeline, AssetSpec
from furina.assets.asset_manifest import AssetManifest, semantic_id_for
from furina.assets.qc import QCEngine
from furina.core import setup_logging, get_logger
import logging

log = get_logger("scripts.generate_assets")


def _spec(posture, emotion="neutral", gaze="front", action="idle", role="base_pose",
          prop=None, tags=None, variant=1):
    return AssetSpec(posture, emotion, gaze, action, variant=variant, prop=prop,
                     role=role, tags=tags or [])


def batch_phase1() -> list[AssetSpec]:
    """P0/P1：核心姿态 + 姿态覆盖（任务书 §35 P0-P1，§7 覆盖率优先）。

    P0 姿态：standing/sitting/lying/sleeping（必做）
    P1 表情变体：happy/curious/thinking 等（这些是高频状态，覆盖优先）
    """
    specs: list[AssetSpec] = []
    # P0 基础姿态 × 中性/开心（高频）
    for pos in ["standing", "sitting", "lying", "sleeping"]:
        for emo in ["neutral", "happy"]:
            specs.append(_spec(pos, emo, "front", "idle", role="base_pose",
                               tags=["P0", "base"]))
    # 高频表情（站立/坐，任务书 §4 expression）
    base_poses = ["standing", "sitting"]
    for pos in base_poses:
        for emo in ["curious", "thinking", "proud", "sleepy", "annoyed", "surprised",
                    "embarrassed", "sad", "excited"]:
            specs.append(_spec(pos, emo, "front", "idle", role="expression",
                               tags=["P1", "expression"]))
    return specs


def batch_phase2() -> list[AssetSpec]:
    """P2/P3：视线（Layer 3）+ 微动作（Layer 4，任务书 §5-6 重点）。

    Gaze 是"活人感"最便宜的素材；Micro 让静态角色"活起来"。
    """
    specs: list[AssetSpec] = []
    # 视线（站立/坐 中性）：user/screen/left/right/up/down
    for pos in ["standing", "sitting"]:
        for gaze in ["user", "screen", "left", "right", "up", "down"]:
            specs.append(_spec(pos, "neutral", gaze, "idle", role="gaze", tags=["P2", "gaze"]))
    # 微动作（站立中性）：blink/yawn/stretch/hair_adjust/look …
    micro_actions = [("yawn", "sleepy"), ("stretch", "sleepy"), ("blink", "neutral"),
                     ("sigh", "sad"), ("giggle", "happy"), ("look", "curious")]
    for act, emo in micro_actions:
        specs.append(_spec("standing", emo, "front", act, role="micro", tags=["P2", "micro"]))
    return specs


def batch_phase3() -> list[AssetSpec]:
    """第二阶段大型动作（任务书 §8-9, §35 核心动作）+ 生活动作。

    每个动作是多帧序列的静态关键帧；动作用 base_pose 的 action 区分，
    后续由 gen_animation 生成多帧序列（Entry/Loop/Exit）。
    """
    specs: list[AssetSpec] = []
    actions = [("drink", "neutral"), ("eat", "happy"), ("read", "focus"),
               ("play", "playful"), ("wave", "happy"), ("think", "thoughtful"),
               ("nap", "sleepy"), ("dance", "happy"), ("excited", "happy")]
    for act, emo in actions:
        specs.append(_spec("standing", emo, "front", act, role="action", tags=["P2", "action"]))
    # 坐/躺/睡 变体姿态（任务书 §3 更多 base pose）
    for pos in ["crouching", "leaning"]:
        for emo in ["neutral", "happy"]:
            specs.append(_spec(pos, emo, "front", "idle", role="base_pose", tags=["P3", "base"]))
    # 互动姿态（任务书 §44 hitbox）
    specs.append(_spec("standing", "happy", "user", "head_touch", role="interaction", tags=["P3"]))
    specs.append(_spec("standing", "surprised", "user", "poke", role="interaction", tags=["P3"]))
    return specs


def default_batch():
    """默认=Phase 1（核心姿态，最小可组合验证，任务书 §34 Phase1）。"""
    return batch_phase1()


def batch_flat100():
    """完整四层素材库（任务书 §3-13）。"""
    return batch_phase1() + batch_phase2() + batch_phase3()


def batch_flat100full():
    """四层素材库 + 道具/更多互动（完整覆盖）。"""
    specs = batch_flat100()
    # 道具（任务书 §22）
    for prop in ["tea", "cake", "book", "phone", "umbrella", "gift"]:
        specs.append(_spec("standing", "happy", "user", f"hold_{prop}", prop=prop,
                           role="prop", tags=["prop"]))
    # 坐姿情绪细化
    for emo in ["proud", "sleepy", "smug"]:
        specs.append(_spec("sitting", emo, "user", "idle", role="expression", tags=["P3"]))
    return specs


def run_qc(cfg, out: str) -> int:
    """视觉+自动质检（plan/2 §24-25）：identity/anatomy/style/transparency。"""
    from furina.assets.asset_manifest import AssetManifest
    from furina.assets.qc import QCEngine
    from furina.llm import get_adapter, LLMMessage, content
    from furina.config import LLMProfile
    import base64, pathlib

    out_dir = cfg.root_dir / out
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        log.error("缺少 manifest: %s", manifest_path)
        return 1
    manifest = AssetManifest.load(manifest_path)
    qc = QCEngine()
    llm = get_adapter("zhipu")(LLMProfile(api_key=cfg.zhipu_api_key)) if cfg.zhipu_api_key else None

    def _data_uri(p) -> str:
        b = pathlib.Path(p).read_bytes()
        return f"data:image/png;base64,{base64.b64encode(b).decode()}"

    def describe(img, prompt):
        if not llm:
            return "0"
        try:
            msgs = [
                LLMMessage("system", content("你是素材质检员，只回答一个 0-5 的整数。")),
                LLMMessage("user", content(("image", _data_uri(img)), prompt)),
            ]
            d = llm.chat(msgs, temperature=0.0, max_tokens=8)
            return d.text.strip()
        except Exception as e:
            log.warning("vision qc err: %s", e)
            return "0"

    report = []
    reject = 0
    for e in manifest.entries:
        p = out_dir / e.path
        r = qc.run_with_vision(p, {"posture": e.posture, "emotion": e.emotion, "gaze": e.gaze},
                               describe)
        report.append({"asset_id": e.asset_id, "verdict": r.verdict, "total": r.total,
                       "transparency": r.transparency, "resolution": r.resolution,
                       "notes": r.notes})
        if r.verdict == "regenerate":
            reject += 1
    import json
    rp = out_dir / "qc-report.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("QC 完成: %d 条, %d 需重生成 -> %s", len(report), reject, rp)
    for r in report:
        log.info("  %-40s %s total=%d", r["asset_id"], r["verdict"], r["total"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="data/assets")
    ap.add_argument("--batch", default="baseline",
                    choices=["baseline", "flat100", "flat100full"],
                    help="standard=17核心; flat100=更多姿态/情绪/视线/动作/道具; flat100full=100图强化补密")
    ap.add_argument("--qc", action="store_true", help="对现有 manifest 跑视觉/自动质检并出报告")
    args = ap.parse_args()

    setup_logging(logging.INFO)
    cfg = load_config()
    if args.qc:
        return run_qc(cfg, args.out)
    if not cfg.agnes_api_key:
        log.error("缺少 AGNES_API_KEY，无法生成素材")
        return 1
    base = cfg.root_dir / "furina-base.png"
    if not base.exists():
        log.error("基座图不存在: %s", base)
        return 1

    agnes = AgnesClient(cfg.agnes_api_key)
    out_dir = cfg.root_dir / args.out
    pipeline = AssetPipeline(base, agnes, out_dir, QCEngine())
    manifest = AssetManifest()
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        manifest = AssetManifest.load(manifest_path)

    specs = batch_100full() if args.batch == "flat100full" else (batch_flat100() if args.batch == "flat100" else default_batch())
    if args.only:
        specs = [s for s in specs if args.only in f"{s.posture}_{s.emotion}"]
    log.info("待生成 %d 个素材 (dry_run=%s, batch=%s) -> %s", len(specs), args.dry_run, args.batch, out_dir)

    # 逐张生成，每张后即保存 manifest（断点续跑、部分结果可用）
    existing = {e.semantic_id(): e for e in manifest.entries}
    done = 0
    skipped = 0
    for spec in specs:
        sem = semantic_id_for(spec.posture, spec.emotion, spec.gaze, "front", spec.action)
        if sem in existing and existing[sem].quality_score > 0:
            skipped += 1
            log.info("  跳过 %s (已有)", sem)
            continue
        try:
            if args.dry_run:
                log.info("[dry-run] %s", sem)
                continue
            entry = pipeline.generate_one(spec)
            manifest.entries.append(entry)
            existing[sem] = entry
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest.save(manifest_path)
            done += 1
            log.info("  + %-40s qc=%d", entry.asset_id, entry.quality_score)
        except Exception as e:
            log.warning("生成失败 %s: %s", sem, e)
            continue
    log.info("完成: 新增 %d, 跳过 %d, manifest=%s 共 %d 条", done, skipped, manifest_path, len(manifest.entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
