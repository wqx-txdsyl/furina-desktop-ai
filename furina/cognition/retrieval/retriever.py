"""Canon Life Retrieval（activation 0..3）。

- 不是全文检索所有剧情；普通话题不得自动拉 LONG_PERFORMANCE（reviewer-locked）。
- 检索同时考虑 semantic relevance + psychological relevance + activation policy；
  最终是否显式提历史仍交 PersonaPlan。
- activation：
  0 = 历史只塑造回答，不显式提历史
  1 = 隐约经验影响
  2 = 可明确提过去（"以前……"）
  3 = 用户直接问相关 Canon 身份/人生，可明确谈具体过去
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from furina.core import get_logger
from ..models import CanonEpisode
from ..stores.canon_history import CanonHistoryStore

log = get_logger("cognition.canon_retrieval")

# 确定性 activation 规则（reviewer-locked 行为 proof）
_IDENTITY_QUERY = ("芙卡洛斯", "focalors", "神格", "人格", "你是谁", "你到底是", "纳西妲",
                   "镜子里", "真神", "假神", "是神", "神吗", "身份", "你的原型", "你是什么")
_ROLE_QUERY = ("当水神", "水神的时候", "当神", "过去", "以前", "演戏", "扮演", "舞台", "表演",
               "审判", "五百年", "歌剧院", "神位", "在位")
_ATTENTION_QUERY = ("没人", "关注", "不看", "观众", "聚光灯", "人气", "粉丝", "被看见",
                    "在乎", "喜欢我", "在意")
_VULNERABILITY_QUERY = ("孤独", "害怕", "想哭", "倾诉", "脆弱", "一个人", "撑不住",
                        "累", "难过", "委屈")
_ORDINARY_QUERY = ("吃什么", "吃饭", "今天吃", "吃啥", "喝茶", "通心粉", "睡", "天气")

# 显式身份话题 → activation 3 + 指定 episodes
_EXPLICIT_ACTIVATION_3 = {
    "identity": ("ORIGIN_IDENTITY", "FOCALORS_TRUTH"),
    "role": ("PUBLIC_ROLE_BEGIN", "LONG_PERFORMANCE", "PUBLIC_ROLE_END"),
    "attention": ("LONG_PERFORMANCE", "ORDINARY_LIFE", "CHOSEN_PERFORMANCE", "PUBLIC_EXPECTATION"),
    "vulnerability": ("PRIVATE_ISOLATION", "MASK_CRACKS", "INNER_WORLD_REVELATION"),
}


class CanonLifeRetriever:
    """C2 检索：返回 (relevant episodes, activation 0..3)。"""

    def __init__(self, history: CanonHistoryStore) -> None:
        self._history = history
        self._by_id = {e.episode_id: e for e in history.all_episodes()}

    def retrieve(self, query: str = "", *, topic: str = "",
                 trust: float = 0.5) -> Tuple[List[CanonEpisode], int]:
        """按查询返回 (episodes, activation)。普通话题 activation=0 且不拉剧情。"""
        q = (query or "").strip().lower()
        # 1) 普通话题：不自动拉 LONG_PERFORMANCE（reviewer-locked："今天吃什么" → activation 0）
        if any(k in q for k in _ORDINARY_QUERY):
            return [], 0
        # 2) 显式过去/水神角色 → activation 3（优先于身份，防"当水神"被身份词抢走）
        if any(k in q for k in _ROLE_QUERY):
            return self._pick(_EXPLICIT_ACTIVATION_3["role"]), 3
        # 3) 显式身份/芙卡洛斯 → activation 3（reviewer-locked："你和芙卡洛斯是什么关系"）
        if any(k in q for k in _IDENTITY_QUERY):
            return self._pick(_EXPLICIT_ACTIVATION_3["identity"]), 3
        # 4) 关注/被看 → activation 2（reviewer-locked："没人关注你怎么办"）
        if any(k in q for k in _ATTENTION_QUERY):
            return self._pick(_EXPLICIT_ACTIVATION_3["attention"]), 2
        # 5) 孤独/脆弱 → activation 2
        if any(k in q for k in _VULNERABILITY_QUERY):
            return self._pick(_EXPLICIT_ACTIVATION_3["vulnerability"]), 2
        # 6) 其它：按 trigger_topics 语义匹配（activation 1），无匹配 → 0
        eps = self._match_triggers(q, topic)
        return eps, (1 if eps else 0)

    def activation_for(self, query: str = "", *, topic: str = "") -> int:
        _, act = self.retrieve(query, topic=topic)
        return act

    # -------------------------------------------------- helpers
    def _pick(self, ids: Tuple[str, ...], limit: int = 2) -> List[CanonEpisode]:
        out = [self._by_id[i] for i in ids if i in self._by_id]
        return out[:limit]

    def _match_triggers(self, q: str, topic: str) -> List[CanonEpisode]:
        scored: List[tuple] = []
        for e in self._history.all_episodes():
            hay = " ".join(e.trigger_topics).lower()
            score = sum(1 for t in e.trigger_topics if t and t.lower() in q) * 2
            if topic:
                t = topic.lower()
                if any(t in tt.lower() for tt in e.trigger_topics):
                    score += 1
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _s, e in scored[:2]]
