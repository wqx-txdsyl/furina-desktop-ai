"""H1 §10：DialogueContextSnapshot —— owner 线程冻结的不可变对话上下文。

所有对话通道（直接用户/喂食/互动/Agent/自主）的 Dialogue 上下文必须在 **owner 线程**冻结为
不可变快照（只含事实副本，不引用可变运行时对象），再交给 worker 线程做 LLM；
worker 只读快照，绝不读 live 运行时状态（关系/情绪/活动/idle/world/记忆）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DialogueContextSnapshot:
    intent: str = ""
    emotion_label: str = ""
    user_text: str = ""
    context: str = ""
    activity: str = ""
    user_initiated: bool = False
    task_mode: bool = False
    solitude: bool = False
    user_present: bool = True
    presence_known: bool = True   # Pre-Manual §8：在场真相已知？（unknown → present=False, solitude=False）
    channel: str = "DIRECT_USER_TURN"
    seq: int = 0
    ingress_seq: Optional[int] = None   # H1-FINAL §2：owner 入口预留的 FIFO 序号（经 say(ingress_seq=) 消费）
    interaction: str = ""               # R2.1 P1-2：互动事实 kind（petting/poke/drag/click）
    agent_state: str = ""               # R2.1 P1-1：当前 Agent 生命周期状态（IDLE/RUNNING/COMPLETED_VERIFIED/…）
    agent_task: str = ""                # R2.1 P1-1：当前活跃 Agent 任务描述（仅执行中）
    memories: Tuple[str, ...] = ()
    world: Tuple[Tuple[str, float], ...] = ()          # flat dict 副本
    relationship: Tuple[Tuple[str, float], ...] = ()   # flat dict 副本
    memory_interp: Tuple[Tuple[str, Any], ...] = ()    # 浅拷贝 dict 副本
    ambient_recent: Tuple[str, ...] = ()

    # -------------------------------------------------- 只读辅助（副本 → 调用参数）
    def memories_list(self) -> List[str]:
        return list(self.memories)

    def world_dict(self) -> Dict[str, Any]:
        return dict(self.world)

    def relationship_dict(self) -> Dict[str, Any]:
        return dict(self.relationship)

    def memory_interp_dict(self) -> Dict[str, Any]:
        return dict(self.memory_interp)

    def say_kwargs(self) -> Dict[str, Any]:
        """展开为 DialogueBrain.say(**kw) 的参数（全部来自冻结副本）。"""
        kw = {
            "intent": self.intent,
            "emotion": self.emotion_label,
            "user_text": self.user_text,
            "context": self.context,
            "activity": self.activity,
            "memories": self.memories_list(),
            "world": self.world_dict(),
            "relationship": self.relationship_dict(),
            "memory_interp": self.memory_interp_dict(),
            "user_initiated": self.user_initiated,
            "task_mode": self.task_mode,
            "solitude": self.solitude,
            "user_present": self.user_present,
            "presence_known": self.presence_known,   # Pre-Manual §8
            "channel": self.channel,
        }
        if self.ingress_seq is not None:
            kw["ingress_seq"] = self.ingress_seq   # H1-FINAL §2：用户输入顺序身份
        if self.interaction:
            kw["interaction"] = self.interaction    # R2.1 P1-2
        if self.agent_state or self.agent_task:
            kw["agent_state"] = self.agent_state    # R2.1 P1-1
            kw["agent_task"] = self.agent_task      # R2.1 P1-1
        return kw

    def ambient_texts(self) -> List[str]:
        return [t for t in self.ambient_recent]


def freeze_flat(d: Optional[Dict[str, Any]]) -> Tuple[Tuple[str, Any], ...]:
    """把 dict 复制为不可变元组（浅拷贝足够：值都是标量）。"""
    if not d:
        return ()
    return tuple((k, v) for k, v in dict(d).items())
