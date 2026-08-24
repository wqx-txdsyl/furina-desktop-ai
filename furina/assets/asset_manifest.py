"""素材 Manifest 与 Resolver（plan/2 §19-21, §17-18）。

素材不是动画，身体能表达的语义单元。程序靠 metadata 找素材，
从不靠文件名猜语义（plan/7 §31）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from furina.core import AssetError, get_logger

log = get_logger("assets.manifest")


# ---------------------------------------------------------------- 命名
def naming_for(posture: str, emotion: str, gaze: str, action: str, variant: int = 1) -> str:
    """统一命名：furina_[posture]_[emotion]_[gaze]_[action]_[variant]（plan/2 §20）。"""
    return f"furina_{posture}_{emotion}_{gaze}_{action}_{variant:02d}"


def semantic_id_for(posture: str, emotion: str, gaze: str, direction: str,
                    action: str, micro: Optional[str] = None) -> str:
    return f"{posture}/{emotion}/{gaze}/{direction}/{action}" + (f"/{micro}" if micro else "")


def _qkey(q: "AssetQuery") -> str:
    """查询的语义 key（用于 ASSET_MISSING 统计）。"""
    return f"{q.posture}/{q.emotion}/{q.gaze}/{q.direction}/{q.action}/{q.micro_motion or '-'}"


# ---------------------------------------------------------------- Manifest 模型
class AssetEntry(BaseModel):
    asset_id: str
    posture: str = "standing"          # standing/sitting/lying/sleeping/crouching/leaning/walking/interacting
    emotion: str = "neutral"
    gaze: str = "front"                # front/left/right/up/down/user
    direction: str = "front"           # front/left/right/back
    action: str = "idle"
    micro_motion: Optional[str] = None
    loop: bool = True
    duration: Optional[float] = None
    interruptible: bool = True
    priority: int = 50
    fps: int = 12
    kind: str = "frame"                # frame / sequence / prop
    frames: List[str] = Field(default_factory=list)   # 序列时的帧文件列表
    tags: List[str] = Field(default_factory=list)
    anchors: Dict[str, List[float]] = Field(default_factory=dict)  # head/body/hand → [x,y] 归一化
    path: str = ""
    quality_score: int = 0
    source: str = "agnes"
    # 四层素材架构（任务书 §3-13）：role 描述素材在动画生命周期里的角色
    role: str = "base_pose"   # base_pose / expression / gaze / micro / action / transition / prop / event
    # 动作生命周期（任务书 §11）：enter / loop / exit 三段，避免“硬切”
    entry_frames: List[str] = Field(default_factory=list)
    loop_frames: List[str] = Field(default_factory=list)
    exit_frames: List[str] = Field(default_factory=list)
    # 过渡（任务书 §25）：由谁到谁
    transition_from: Optional[str] = None
    transition_to: Optional[str] = None

    def semantic_id(self) -> str:
        return semantic_id_for(self.posture, self.emotion, self.gaze, self.direction,
                               self.action, self.micro_motion)


class AssetManifest(BaseModel):
    character: str = "furina"
    version: str = "v1"
    entries: List[AssetEntry] = Field(default_factory=list)
    identity_anchor: str = "furina-base.png"

    def index(self) -> Dict[str, AssetEntry]:
        return {e.asset_id: e for e in self.entries}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "AssetManifest":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Resolver
@dataclass
class AssetQuery:
    posture: str
    emotion: str
    gaze: str = "front"
    direction: str = "front"
    action: str = "idle"
    micro_motion: Optional[str] = None
    loop: bool = True


class AssetResolver:
    """按优先级匹配最合适素材（plan/2 §18）。

    Exact → Same Posture → Same Emotion → Same Action → Nearest Semantic → Neutral fallback。
    """

    def __init__(self, manifest: AssetManifest) -> None:
        self.manifest = manifest
        self._missing: Dict[str, int] = {}   # 统计缺失语义（ASSET_MISSING，plan/2 §26）

    @property
    def missing(self) -> Dict[str, int]:
        return dict(self._missing)

    def record_missing(self, key: str) -> None:
        self._missing[key] = self._missing.get(key, 0) + 1

    def resolve(self, q: AssetQuery) -> Optional[AssetEntry]:
        entries = self.manifest.entries
        if not entries:
            # 无任何素材：记录缺失，但不返回 idle（上层据此用基座图 fallback）
            self.record_missing(_qkey(q))
            return None
        # 1. Exact
        for e in entries:
            if self._exact(e, q):
                return e
        # 2. Same posture (+emotion) + action
        for e in entries:
            if e.posture == q.posture and e.emotion == q.emotion and e.action == q.action:
                return e
        # 3. Same posture + action（动作优先，保证“drink 请求”不落到无关的 idle 站姿）
        for e in entries:
            if e.posture == q.posture and e.action == q.action:
                return e
        # 4. Same posture
        for e in entries:
            if e.posture == q.posture:
                return e
        # 5. Same action（任意姿势，仍忠实地表达“要做这个动作”）
        for e in entries:
            if e.action == q.action:
                return e
        # 6. Same emotion
        for e in entries:
            if e.emotion == q.emotion:
                return e
        # 7. Nearest：任意站立中立（不是 idle 语义，只是最接近的可视化兜底）——仍记缺失
        self.record_missing(_qkey(q))
        for e in entries:
            if e.posture == "standing" and e.emotion == "neutral":
                return e
        return entries[0]

    @staticmethod
    def _exact(e: AssetEntry, q: AssetQuery) -> bool:
        return (
            e.posture == q.posture
            and e.emotion == q.emotion
            and e.gaze == q.gaze
            and e.direction == q.direction
            and e.action == q.action
            and (e.micro_motion == q.micro_motion)
        )

    def load_asset_file(self, entry: AssetEntry, base_dir: Path) -> Optional[Path]:
        if not entry.path:
            return None
        p = base_dir / entry.path
        return p if p.exists() else None
