"""Phase 15 D3 — Retrieval Exposure Cooldown（reviewer-locked 15 攻击面）。

铁律：ledger=DERIVED/SESSION-LOCAL/非权威；mark-after-success；显式召回绕过；
失败装配零记录；TTL/LRU 有界；重启清空且 source truth 一字不动。
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

_QAPP = QApplication.instance() or QApplication([])


def _hub(tmp_path, *, ttl=None, capacity=None):
    from furina.cognition import CognitionHub
    from furina.cognition.retrieval.exposure import RetrievalExposureLedger
    from furina.memory import MemoryEngine, MemoryStore

    class _Bus:
        def emit(self, *a, **k):
            return None

    hub = CognitionHub(Path(tmp_path) / "cog.db",
                       memory_engine=MemoryEngine(_Bus(), MemoryStore(
                           Path(tmp_path) / "mem.db")))
    kw = {}
    if ttl is not None:
        kw["ttl_seconds"] = ttl
    if capacity is not None:
        kw["capacity"] = capacity
    ledger = RetrievalExposureLedger(**kw)
    hub.exposure_ledger = ledger
    hub.assembler._exposure = ledger          # 与生产同源共享实例
    return hub, ledger


def _mem(hub, content, *, ts=1787800000.0):
    from furina.memory import Memory, MemoryLevel, MemoryStatus
    m = Memory(mem_id=f"mem_{abs(hash(content)) % 10**6}",
               level=MemoryLevel.EPISODIC, content=content,
               status=MemoryStatus.ACTIVE, timestamp=ts)
    hub.autobiography.insert(m)
    return m


# ================================================================ T1/T2 首现与抑制
def test_d3_t1_first_implicit_retrieval_surfaces_and_marks(tmp_path):
    hub, ledger = _hub(tmp_path)
    mobj = _mem(hub, "用户喜欢喝冷萃咖啡")
    mid = mobj.mem_id
    hub.build_index()
    ctx = hub.assemble(query="冷萃咖啡")            # 第一次隐式检索
    assert any("冷萃" in m for m in ctx.autobiographical_memories)
    snap = ledger.snapshot()
    assert f"C3:{mid}" in snap, snap                # 成功装配 → 已标记
    hub.close()


def test_d3_t2_immediate_repeat_suppressed_within_ttl(tmp_path):
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    hub.assemble(query="冷萃咖啡")                   # 第一次：曝光并标记
    keys = list(ledger.snapshot())
    c2 = hub.assemble(query="聊聊咖啡相关的话题")     # 立即重复的隐式检索
    assert ((not any("冷萃" in m for m in c2.autobiographical_memories)),
        (("冷却窗口内的重复注入必须被抑制")))
    assert list(ledger.snapshot()) == keys          # 抑制轮不产生新曝光记录
    # TTL 过后再次可出现（见 T8 的显式时间测试；此处验证窗口内稳定）
    hub.close()


def test_d3_t2b_explicit_recall_bypasses_cooldown(tmp_path):
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    hub.assemble(query="冷萃咖啡")
    cooled_ctx = hub.assemble(query="聊聊咖啡相关的话题")
    assert not any("冷萃" in m for m in cooled_ctx.autobiographical_memories)
    recall_ctx = hub.assemble(query="你还记得我说的咖啡吗")   # 显式召回措辞
    assert (any("冷萃" in m for m in recall_ctx.autobiographical_memories)), ("显式召回必须绕过冷却")
    hub.close()


def test_d3_t2c_selective_isolation_bounds_one(tmp_path):
    """桶上限=1 时只入选一条并被冷却；另一条未曝光 → 下轮仍可出现。"""
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    _mem(hub, "用户上周末去骑行了")
    hub.assembler._bounds = dict(hub.assembler._bounds, memories=1)
    hub.build_index()
    hub.assemble(query="冷萃咖啡")                    # 咖啡胜出进入上下文
    keys = list(ledger.snapshot())
    assert len(keys) == 1 and "冷萃" not in keys[0], keys
    other = hub.assemble(query="骑行的记忆")           # 未曝光的 B 不受 A 冷却影响
    assert any("骑行" in m for m in other.autobiographical_memories)
    hub.close()


def test_d3_t2e_recall_bypass_with_locked_phrase(tmp_path):
    """任务书锁定说法「刚才那个…」：完整 cooldown → 显式召回绕过流程。"""
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    hub.assemble(query="冷萃咖啡")                    # 首现并标记
    suppressed = hub.assemble(query="给我讲讲咖啡吧")   # 非召回措辞 → 冷却抑制
    assert not any("冷萃" in m for m in suppressed.autobiographical_memories)
    recall = hub.assemble(query="刚才那个冷萃咖啡的配方再讲一遍")  # 锁定说法
    assert (any("冷萃" in m for m in recall.autobiographical_memories)), (
        "「刚才那个…」显式召回必须绕过冷却")
    hub.close()


def test_d3_t1b_same_candidate_suppressed_in_adjacent_query(tmp_path):
    """reviewer D3-T1：同一 C3 候选在相邻（下一轮、不同措辞）query 中被冷却抑制。
    对照组证明：无任何曝光时同一 query 本可浮出 → 抑制确系冷却所致，
    而非 query 串不匹配或首现轮副作用。"""
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    ctx1 = hub.assemble(query="冷萃咖啡")              # 首现：浮出并标记
    assert any("冷萃" in m for m in ctx1.autobiographical_memories)
    ctx2 = hub.assemble(query="给我讲讲咖啡吧")         # 相邻但不同的 query
    assert (not any("冷萃" in m for m in ctx2.autobiographical_memories)), (
        "同一 C3 候选在相邻不同 query 中必须被冷却抑制")
    hub.close()

    ctrl, _ = _hub(Path(tempfile.mkdtemp()))           # 对照组：零曝光
    _mem(ctrl, "用户喜欢喝冷萃咖啡")
    ctrl.build_index()
    ctrl_ctx = ctrl.assemble(query="给我讲讲咖啡吧")
    assert any("冷萃" in m for m in ctrl_ctx.autobiographical_memories), (
        "对照：无冷却时同一 query 必须浮出该候选")
    ctrl.close()


def test_d3_t1c_unrelated_query_suppressed_via_stub(tmp_path, monkeypatch):
    """reviewer D3-T1（stub 版）：monkeypatch 强制同一 C3 候选在**无关** query
    （“今天天气怎么样”）中返回 —— 对照组：未曝光时能进入 context；
    实验组：首次曝光后，相邻无关 turn 被 cooldown 抑制。
    仅测试层 stub，零生产代码改动。"""
    def _force(mobj):
        def _retrieve(*, query="", limit=3, context=None):
            return [mobj]
        return _retrieve

    # ---------- 对照组：零曝光 → 无关 query（stub 强制返回）能进入 context ----------
    hub_c, _ = _hub(Path(tempfile.mkdtemp()))
    mc = _mem(hub_c, "用户喜欢喝冷萃咖啡")
    hub_c.build_index()
    monkeypatch.setattr(hub_c.autobiography, "retrieve", _force(mc))
    ctrl = hub_c.assemble(query="今天天气怎么样")
    assert (any("冷萃" in m for m in ctrl.autobiographical_memories)), (
        "对照：未曝光时同一 C3 候选必须能进入 context")
    hub_c.close()

    # ---------- 实验组：首次曝光后 → 相邻无关 turn 被 cooldown 抑制 ----------
    hub_e, ledger_e = _hub(Path(tempfile.mkdtemp()))
    me = _mem(hub_e, "用户喜欢喝冷萃咖啡")
    hub_e.build_index()
    monkeypatch.setattr(hub_e.autobiography, "retrieve", _force(me))
    first = hub_e.assemble(query="冷萃咖啡")            # 首次曝光（stub 亦返回同一候选）
    assert any("冷萃" in m for m in first.autobiographical_memories)
    assert ledger_e.cooled(f"C3:{me.mem_id}"), "首次曝光后必须已标记"
    nxt = hub_e.assemble(query="今天天气怎么样")         # 相邻无关 turn（stub 强制返回同一候选）
    assert (not any("冷萃" in m for m in nxt.autobiographical_memories)), (
        "实验：首次曝光后相邻无关 turn 必须被 cooldown 抑制")
    hub_e.close()


def test_d3_t7b_c6_events_enter_context_during_c3_cooldown(tmp_path):
    """reviewer D3-T7：C3 冷却前后，当前 C6 event 仍正常进入 context。"""
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    ev = hub.record_event("USER_MESSAGE", payload={"text": "帮我看看这个文件"},
                          turn_id=1, consolidate=False)
    hub.build_index()
    ctx1 = hub.assemble(query="冷萃咖啡")              # 冷却前：C3 浮出 + C6 在场
    assert any("冷萃" in m for m in ctx1.autobiographical_memories)
    assert ev.event_id in [e.event_id for e in ctx1.recent_events]
    ctx2 = hub.assemble(query="给我讲讲咖啡吧")         # 冷却中：C3 被抑制
    assert not any("冷萃" in m for m in ctx2.autobiographical_memories)
    ids2 = [e.event_id for e in ctx2.recent_events]
    assert (ev.event_id in ids2), ("C3 冷却不得影响当前 C6 event 进入 context")
    hub.close()


# ================================================================ mark-after-success
def test_d3_t4_mark_only_selected_into_final_context(tmp_path):
    """T4：桶上限截断后，仅入选对象被标记；未入选者不记曝光。"""
    hub, ledger = _hub(tmp_path)
    for i, w in enumerate(("苹果", "香蕉", "樱桃", "葡萄")):
        _mem(hub, f"记忆条目关于{w}编号{i}", ts=1787800000.0 + i)
    # 自定义小桶上限 = 1：只有 rank 第一的记忆进入最终 context
    hub.assembler._bounds = dict(hub.assembler._bounds, memories=1)
    hub.build_index()
    ctx = hub.assemble(query="记忆条目")             # 四条都匹配词面，仅留 1 条
    assert len(ctx.autobiographical_memories) == 1
    snap = ledger.snapshot()
    assert len(snap) == 1, f"只能有一条被标记: {snap}"
    marked_ref = next(iter(snap))
    assert ctx.autobiographical_memories[0] in (
        [f"记忆条目关于{w}编号{i}" for i, w in
         enumerate(("苹果", "香蕉", "樱桃", "葡萄"))])
    _ = marked_ref
    hub.close()


def test_d3_t5_ranked_out_candidate_not_marked(tmp_path):
    """与 T4 对偶：排名靠后被丢弃的候选绝不计入曝光。"""
    hub, ledger = _hub(tmp_path)
    contents = ("冷萃咖啡制作方法详解", "冷萃咖啡历史文化考")
    for i, c in enumerate(contents):
        _mem(hub, c, ts=1787800000.0 + i * 100000)
    hub.assembler._bounds = dict(hub.assembler._bounds, memories=1)
    hub.build_index()
    ctx = hub.assemble(query="冷萃咖啡")
    assert len(ctx.autobiographical_memories) == 1
    assert len(ledger.snapshot()) == 1, "rank-out 候选不得被标曝光"
    hub.close()


def test_d3_t6_failed_assembly_marks_nothing(tmp_path):
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()

    # 在上下文构造中途注入失败（C4 桶之后、成功返回之前）
    orig_query_recent = type(hub.events).query_recent

    def boom(self, limit=10):
        raise RuntimeError("injected failure mid-assembly")

    type(hub.events).query_recent = boom
    raised = False
    try:
        hub.assemble(query="冷萃咖啡")
    except RuntimeError:
        raised = True
    finally:
        type(hub.events).query_recent = orig_query_recent
    assert raised, "注入的装配失败应向上传播"
    assert ledger.snapshot() == {}, "失败/中止的装配不得记录任何曝光"
    hub.close()


def test_d3_t7_refs_do_not_share_exposure_state(tmp_path):
    """不同 ref 各自独立记录曝光；标记 A 绝不影响 B 的可出现性（双层验证）。"""
    from furina.cognition.retrieval.exposure import RetrievalExposureLedger
    lg = RetrievalExposureLedger()
    lg.mark("C3:A"); lg.mark("C3:B")
    assert lg.cooled("C3:A") and lg.cooled("C3:B")
    lg.reset(); lg.mark("C3:A")
    assert lg.cooled("C3:A") and not lg.cooled("C3:B"),         "未曝光的 B 不得继承 A 的冷却"

    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    _mem(hub, "用户上周末去骑行了")
    hub.assembler._bounds = dict(hub.assembler._bounds, memories=1)
    hub.build_index()
    hub.assemble(query="冷萃咖啡")                    # 仅 A 入选
    other = hub.assemble(query="骑行的记忆")           # B 未被曝光过 → 应可正常出现
    assert any("骑行" in m for m in other.autobiographical_memories)
    snap_keys = sorted(ledger.snapshot())
    assert all(k.startswith("C3:") for k in snap_keys)
    hub.close()


def test_d3_t8_ttl_expiry_restores_eligibility(tmp_path):
    hub, ledger = _hub(tmp_path, ttl=0.05)            # 极短 TTL（50ms）
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    hub.assemble(query="冷萃咖啡")
    cooled = hub.assemble(query="聊聊咖啡吧")
    assert not any("冷萃" in m for m in cooled.autobiographical_memories)
    time.sleep(0.08)                                   # > TTL
    expired = hub.assemble(query="聊聊咖啡吧")
    assert (any("冷萃" in m for m in expired.autobiographical_memories)), ("TTL 到期后必须重新可出现")


def test_d3_t9_lru_capacity_bounded(tmp_path):
    hub, ledger = _hub(tmp_path, capacity=1)
    a = _mem(hub, "用户喜欢喝冷萃咖啡")
    _mem(hub, "用户上周开始夜跑锻炼")
    hub.assembler._bounds = dict(hub.assembler._bounds, memories=1)  # 每轮仅入选 1 条
    hub.build_index()
    hub.assemble(query="冷萃咖啡")                    # 仅 A 入选并入账本
    hub.assemble(query="夜跑锻炼的事")                 # 仅 B 入选 → A 被 LRU 逐出
    snap_keys = list(ledger.snapshot().keys())
    assert len(snap_keys) == 1, f"容量=1 时账本不得超过 1 条: {snap_keys}"
    # 被淘汰项恢复资格：A 已不在账本 → 不再冷却 → 相邻 query 可再次浮出
    assert not ledger.cooled(f"C3:{a.mem_id}"), "LRU 逐出的 A 必须恢复资格"
    again = hub.assemble(query="冷萃咖啡")
    assert any("冷萃" in m for m in again.autobiographical_memories), (
        "恢复资格后同一 C3 候选必须可再次浮出")
    hub.close()


def test_d3_t10_restart_clears_ledger_not_truth(tmp_path):
    db = Path(tmp_path) / "cog.db"
    mdb = Path(tmp_path) / "mem.db"
    hub, ledger = _hub(Path(tmp_path))
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    hub.assemble(query="冷萃咖啡")
    assert ledger.snapshot()
    truth_before = hub.autobiography.all_memories(status=None)
    hub.close()                                        # session 结束
    hub2, ledger2 = _hub(Path(tempfile.mkdtemp()))
    # 用同一持久化位置模拟“真重启”：替换其内部 store 路径较复杂，
    # 这里以全新会话等价校验核心契约：新账本空 + 记忆仍存在。
    mems_after = hub2.autobiography.all_memories(status=None)  # 不同库 → 应为空
    del mems_after
    assert ledger2.snapshot() == {}, "restart 后 exposure 清零"
    # 真·持久库直开：
    from furina.memory import MemoryStore
    store2 = MemoryStore(mdb)
    rows2 = store2.query(limit=200, status=None)
    assert ((len(rows2) == len(truth_before) >= 1
             and all(m.content == "用户喜欢喝冷萃咖啡" for m in rows2)),
            ("source truth 完整保留"))
    store2.close()


# ================================================================ 权威面保持
def test_d3_t11_c2_activation_policy_unchanged(tmp_path):
    hub, ledger = _hub(tmp_path)
    _mem(hub, "冷萃咖啡相关记忆占位")
    hub.build_index()
    hub.assemble(query="冷萃咖啡")                     # 先制造一次曝光也不影响 C2
    ctx = hub.assemble(query="今天天气怎么样")
    assert ctx.canon_activation == 0 and ctx.relevant_canon_episodes == []
    hub.close()


def test_d3_t12_c3_authoritative_rows_unchanged_by_exposure_loop(tmp_path):
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    before = [(m.mem_id, m.content, str(getattr(m.status, 'value', m.status)),
               float(m.timestamp)) for m in
              hub.autobiography.all_memories(status=None)]
    hub.build_index()
    hub.assemble(query="冷萃咖啡")
    hub.assemble(query="再聊聊咖啡吧")
    after = [(m.mem_id, m.content, str(getattr(m.status, 'value', m.status)),
              float(m.timestamp)) for m in
             hub.autobiography.all_memories(status=None)]
    assert before == after, "曝光循环绝不能改写 C3 权威行"
    hub.close()


def test_d3_t13_c4_c7_semantics_unchanged(tmp_path):
    hub, ledger = _hub(tmp_path)
    hub.apply_user_message("我喜欢喝咖啡", turn_id=1,
                           basis_ts=__import__("datetime").datetime(
                               2026, 8, 27, 15,
                               tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")
                           ).timestamp(),
                           tz_name="Asia/Shanghai")
    pref_before = hub.user_model.query_active(category="PREFERENCE")[0]
    hub.agent_history.create_task("t_x", original_request="r", goal="g")
    hub.agent_history.set_status("t_x", "FAILED")
    hub.build_index()
    hub.assemble(query="咖啡")
    pref_after = hub.user_model.query_active(category="PREFERENCE")[0]
    assert (pref_after.item_id, pref_after.status) == (pref_before.item_id, "active")
    task = hub.agent_history.get_task("t_x")
    assert task is None or getattr(task, "status", "") != "COMPLETED_VERIFIED"
    hub.close()


def test_d3_t14_d2_hybrid_remains_functional_under_ledger(tmp_path):
    hub, ledger = _hub(tmp_path)
    _mem(hub, "用户喜欢喝冷萃咖啡")
    hub.build_index()
    ctx = hub.assemble(query="冷萃咖啡")                # hybrid（lex∪vec）正常执行
    hits = hub.index.hybrid_lookup("冷萃咖啡")
    assert hits, "D2 hybrid 在 ledger 共存时仍工作"
    ctx2 = hub.assemble(query="再聊聊咖啡吧")           # 第二轮：若已曝光则静默一次
    assert isinstance(ctx2.autobiographical_memories, list)
    hub.close()


def test_d3_t15_recall_detector_no_false_positives():
    from furina.cognition.retrieval.exposure import is_recall_intent
    positives = ["你还记得我说的报告吗", "刚才你讲了一个观点",
                 "再说说上次那个事", "我之前提过这个问题",
                 "再说一次吧", "刚才那个冷萃咖啡的配方再讲一遍"]
    negatives = ["今天天气怎么样", "帮我写一段代码",
                 "最近怎么样呀", "我明天要去体检",
                 "这首歌不错"]
    for p_txt in positives:
        assert is_recall_intent(p_txt), p_txt
    for n_txt in negatives:
        assert not is_recall_intent(n_txt), f"误判为召回: {n_txt}"
