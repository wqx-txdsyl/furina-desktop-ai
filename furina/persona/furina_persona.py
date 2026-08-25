"""芙宁娜人格库（启动时固定）与 Prompt 组合器（R2.2.1 §3：Canon 兼容层）。

R2.2.1：本模块**不再维护独立人物事实**——`FURINA_PERSONA` 是 `furina_canon.SYSTEM_PERSONA`
的兼容别名（唯一 Canon 源在 furina/persona/furina_canon.py）。行为人格配置保留。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .furina_canon import SYSTEM_PERSONA as FURINA_PERSONA  # 唯一 Canon prompt 源


# 行为人格配置（Life Simulation P2：Personality → Motivation 确定性权重，不用 LLM）。
# 芙宁娜：骄傲爱表现 → 社交/关注度高；有自己的小日子 → 独立与自主探索；有点玩心。
# 范围 0..1；0.5=中性。这些值稳定、不由 LLM 生成、不人格学习。
FURINA_BEHAVIOR_PERSONALITY = {
    "self_activity_preference": 0.6,   # 有自己的小日子
    "social_activity_preference": 0.7, # 爱表现、爱陪用户
    "exploration_preference": 0.55,    # 有点好奇
    "play_preference": 0.6,            # 有点玩心
    "helpfulness": 0.7,                # 骄傲地想帮忙
    "curiosity": 0.6,
    "attention_seeking": 0.65,         # 爱被关注
    "independence": 0.55,
}


def __getattr__(name):
    """兼容旧引用：FURINA_PERSONA / compose_request 之外，允许拿人格配置。"""
    if name == "FURINA_BEHAVIOR_PERSONALITY":
        return FURINA_BEHAVIOR_PERSONALITY
    raise AttributeError(name)


def _state_block(state: Dict[str, Any]) -> str:
    return (
        f"【当前状态】\n"
        f"生活状态: {state.get('macro')} / {state.get('activity')}\n"
        f"情绪: {state.get('emotion')} (心情 {state.get('mood')})\n"
        f"注意力: {state.get('attention', {}).get('target') if isinstance(state.get('attention'), dict) else state.get('attention')}\n"
        f"活跃窗口: {state.get('active_window', {}).get('app')} - {state.get('active_window', {}).get('title')}\n"
        f"用户空闲: {state.get('user_idle')} 秒"
    )


def compose_request(
    *,
    persona: str = FURINA_PERSONA,
    state: Dict[str, Any] | None = None,
    memories: List[str] | None = None,
    environment: Dict[str, Any] | None = None,
    available_actions: List[str] | None = None,
    task: str = "",
    schema: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """把六块拼成一个请求。

    返回 {"system": str, "user": str} 或带结构说明；调用方决定如何传给 adapter。
    """
    parts: List[str] = []
    if state:
        parts.append(_state_block(state))
    if memories:
        parts.append("【相关记忆】\n" + "\n".join(f"- {m}" for m in memories[:8]))
    if environment:
        parts.append("【当前环境】\n" + "\n".join(f"- {k}: {v}" for k, v in environment.items()))
    if available_actions:
        parts.append("【允许的行为枚举】(只能从这些里选)\n" + ", ".join(available_actions))
    if task:
        parts.append(f"【当前任务/请求】\n{task}")
    user = "\n\n".join(parts) if parts else "（无额外上下文）"
    return {"system": persona, "user": user}
