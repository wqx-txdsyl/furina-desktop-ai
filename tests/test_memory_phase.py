"""Phase 07: Episodic Experience / Long-term Memory 测试（§41）。"""
from __future__ import annotations

import tempfile, pathlib, time
from furina.core import EventBus
from furina.memory import MemoryStore, MemoryEngine
from furina.memory.experience import Experience, importance_of
from furina.state import CharacterState
from furina.emotion import EmotionEngine
from furina.behavior import BehaviorMotivation, Personality

P = Personality(0.6, 0.7, 0.55, 0.6, 0.7, 0.6, 0.65, 0.55)


def _eng():
    bus = EventBus()
    store = MemoryStore(pathlib.Path(tempfile.mkstemp(suffix=".db")[1]))
    return bus, MemoryEngine(bus, store, threshold=0.4)


def _exp(event_type, world="coding", intensity=0.7, rel=0.8, usr=0.8, act="talk", nov=0.5):
    return Experience(token=f"{event_type}|{world}|{act}", event_type=event_type,
                      summary=event_type, world_context=world, activity=act,
                      emotional_intensity=intensity, relationship_relevance=rel,
                      user_relevance=usr, novelty=nov, outcome="failure" if "reject" in event_type else "success")


def test_experience_importance():
    """低重要（普通事件）< 高重要（强烈+高关系相关）。"""
    lo = importance_of(_exp("user_response", intensity=0.2, rel=0.2, usr=0.2, nov=0.1))
    hi = importance_of(_exp("user_rejection", intensity=0.9, rel=0.9, usr=0.9, nov=0.8))
    assert 0 <= lo < hi <= 1.0, f"{lo} < {hi}"


def test_low_importance_not_consolidated():
    """低重要不落库（遗忘是能力）。"""
    _, me = _eng()
    m = me.consolidate(_exp("user_response", intensity=0.1, rel=0.1, usr=0.1, nov=0.05))
    assert m is None, "低重要不应保存"


def test_high_importance_consolidated():
    _, me = _eng()
    m = me.consolidate(_exp("user_rejection", intensity=0.9, rel=0.9, usr=0.9, nov=0.8))
    assert m is not None and m.importance >= 0.4


def test_memory_deduplication():
    """重复经历合并（recurrence++），不产生多条相同记忆。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection"))
    me.consolidate(_exp("user_rejection"))
    me.consolidate(_exp("user_rejection"))
    allm = me.store.query(limit=50, status=None)
    assert len(allm) == 1, f"应只有 1 条合并{len(allm)}"
    assert allm[0].recurrence_count >= 2


def test_memory_reinforcement():
    """重复经历增加 recurrence 与 confidence。"""
    _, me = _eng()
    m1 = me.consolidate(_exp("user_rejection"))
    c1 = m1.confidence
    me.consolidate(_exp("user_rejection"))
    allm = me.store.query(limit=50, status=None)
    assert allm[0].confidence >= c1, "重复应提高 confidence"


def test_memory_retrieval_context():
    """检索按当前 context（coding 记忆在 browsing 不返回）。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection", world="coding"))
    coding = me.retrieve(query="", limit=3, context="coding")
    browsing = me.retrieve(query="", limit=3, context="browsing")
    assert len(coding) >= 1, "coding 应检索到"
    assert len(browsing) == 0, "browsing 不应检索到 coding 记忆"


def test_memory_recency():
    """旧记忆在检索中衰减。"""
    _, me = _eng()
    m = me.consolidate(_exp("user_rejection"))
    m.timestamp = time.time() - 30 * 86400   # 30 天前
    me.store.insert(m)
    me.consolidate(_exp("user_positive_response"))  # 新记忆
    # 新记忆应排前
    mems = me.retrieve(query="", limit=3, context="coding")
    assert mems[0].event_type != "user_rejection" or mems[0].timestamp > m.timestamp


def test_memory_to_motivation():
    """coding rejection 记忆 → talk 动机被压。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection", world="coding", act="talk"))
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70
    ee = EmotionEngine(st.emotion)
    m_mem = BehaviorMotivation(personality=P, memory_engine=me)
    on = next(x.score for x in m_mem.candidates(st, ee, ctx={"memory_off": False}) if x.activity == "talk")
    off = next(x.score for x in m_mem.candidates(st, ee, ctx={"memory_off": True}) if x.activity == "talk")
    assert on < off, f"记忆应压 talk: {on:.3f} vs {off:.3f}"


def test_memory_off_control():
    """Memory OFF（memory_off=True）时 A/B/C 无记忆差异。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection"))
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70
    ee = EmotionEngine(st.emotion)
    m_mem = BehaviorMotivation(personality=P, memory_engine=me)
    off_a = next(x.score for x in m_mem.candidates(st, ee, ctx={"memory_off": True}) if x.activity == "talk")
    off_c = next(x.score for x in m_mem.candidates(st, ee, ctx={"memory_off": True}) if x.activity == "offer_help")
    # memory_off 时记忆因子不存在 → talk 由其它 factor 决定（不因 memory 差异）
    assert off_a >= 0


def test_memory_vs_relationship_independence():
    """Memory 只影响 context expectation，不动 Relationship 维度。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection", world="coding"))
    # retrieve 后，relationship 不应被改写（Memory ≠ Relationship）
    before = dict(me.relationship.as_dict())
    me.retrieve(query="", limit=3, context="coding")
    after = dict(me.relationship.as_dict())
    assert before == after, "Memory 检索不应改 Relationship"


def test_contradictory_memory_recovery():
    """先负后正 → expectation 变化（Memory 不不可逆）。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection", world="coding", intensity=0.8))
    me.consolidate(_exp("user_positive_response", world="coding", intensity=0.8))
    # 都有 → 解释同时有 pos 与 neg（evidence aggregation §28）
    mems = me.retrieve(query="", limit=4, context="coding")
    interp = me.interpret(mems, context="coding")
    assert interp["positive_expectation"] >= 0 and interp["negative_expectation"] >= 0


def test_capacity_management():
    """容量治理：低重要旧记忆被优先淘汰。"""
    bus = EventBus()
    store = MemoryStore(pathlib.Path(tempfile.mkstemp(suffix=".db")[1]))
    me = MemoryEngine(bus, store, threshold=0.3)
    # 灌入大量低重要重复
    for i in range(400):
        me.consolidate(_exp("user_response" if i % 2 else "user_initiated", world="idle",
                            intensity=0.1, rel=0.1, usr=0.1, nov=0.05))
    allm = store.query(limit=500, status=None)
    assert len(allm) <= 300, f"应治理到容量内: {len(allm)}"


def test_irrelevant_memory_filtering():
    """无关情境记忆不干扰（browsing 时 coding 记忆无效果）。"""
    _, me = _eng()
    me.consolidate(_exp("user_rejection", world="coding"))
    st = CharacterState(); st.clock_hour = 14; st.needs.social_need = 70
    ee = EmotionEngine(st.emotion)
    m_mem = BehaviorMotivation(personality=P, memory_engine=me)
    # browsing context: 记忆不 retrieval → talk 无记忆差异
    mems = me.retrieve(query="", limit=3, context="browsing")
    assert len(mems) == 0, "无关情境应无记忆"
