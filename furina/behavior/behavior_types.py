"""行为类型定义（legacy-plan/3 §6-7）。

行为不是动画，只是意图；动画只是行为的一个可能实现。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


class BehaviorState(str, enum.Enum):
    INTENT = "intent"        # 提出意图
    PREPARE = "prepare"      # 准备
    MOVE = "move"            # 移动
    ACT = "act"              # 执行
    WAIT = "wait"            # 等待
    REACT = "react"          # 反应
    COMPLETE = "complete"    # 完成
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass
class BehaviorDefinition:
    """一个行为定义：condition / utility / duration / interruptible / cooldown / effects。"""

    action: str
    # 权重：从状态(CharacterState)计算得分
    utility_fn: Optional[Callable[[dict], float]] = None
    base_utility: float = 0.0
    priority: int = 4                 # 对齐 state.P_*
    duration: float = 10.0
    interruptible: bool = True
    cooldown: float = 0.0             # 秒
    effects: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    # 可执行动画/姿态提示（表现层），由 Runtime 消费
    posture_hint: str = "standing"
    # 行为链（legacy-plan/3 §22）：本行为结束后衔接到的下一个行为（若条件满足）
    chain_to: Optional[str] = None
    chain_if: Optional[Callable[[dict], bool]] = None


@dataclass
class BehaviorResult:
    action: str
    outcome: str = "ok"               # ok / interrupted / failed
    note: str = ""
    reason: str = ""
