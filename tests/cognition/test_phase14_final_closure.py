"""Phase 14 Final Closure Patch — reviewer-locked tests（C2 / C3 / C4）。

这些测试必须在 BEFORE 版本稳定失败、在 AFTER 版本稳定通过：
- C2-T1..T5：canonical source/evidence attribution 唯一且无矛盾（FUR-006 / FUR-052）；
- C3-T1..T7：Scheduler bypass 消失、单一形成权威、exact provenance、exactly-once、
  objective interaction semantics（ignore 来自真实 observed social bid，非 timer 凭空制造）；
- C3-T8：interaction 记忆内容必须来自可观察事件 payload（poke/drag 不得记成"摸头"）；
- C4-T1..T5：preference supersede / plan complete 的 lifecycle transition 有 canonical
  trigger event provenance，且持久化可重载。

全部经由 production 对象（CognitionHub / CanonHistoryStore / Scheduler）驱动，
不复制测试字典、不替生产代码补 provenance。
"""
from __future__ import annotations

import ast
import tempfile
import time
from pathlib import Path

from furina.core import EventBus
from furina.cognition import CognitionHub
from furina.emotion import EmotionEngine
from furina.memory import MemoryEngine, MemoryStore
from furina.relationship.engine import RelationshipEngine
from furina.runtime.scheduler import Scheduler
from furina.state import StateEngine

_REPO = Path(__file__).resolve().parents[2]


class _Bus:
    def emit(self, *a, **k):
        return None


def _hub(tmp_path) -> CognitionHub:
    store = MemoryStore(tmp_path / "mem.db")
    engine = MemoryEngine(_Bus(), store)
    return CognitionHub(tmp_path / "cog.db", memory_engine=engine,
                        relationship_engine=RelationshipEngine())


def _sched_with_cog(tmp_path):
    """真实 Scheduler + CognitionHub 装配（生产路由形态）。"""
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    store = MemoryStore(tmp_path / "mem.db")
    me = MemoryEngine(_Bus(), store)
    rel = RelationshipEngine()
    hub = CognitionHub(tmp_path / "cog.db", memory_engine=me, relationship_engine=rel)
    sched = Scheduler(bus, se, None, None, me, None, None,
                      emotion_engine=emo, relationship_engine=rel, cognition=hub)
    # 有效在场（begin_social_bid 的客观前提：真实 OS 空闲样本 + present）
    sched.world_perc.state.idle_available = True
    sched.world_perc.state.user_present = True
    sched.world_perc.state.user_active = True
    sched.world_perc.state.user_idle_seconds = 5.0
    sched.world_perc._has_valid_idle = True
    return sched, hub, me


def _ignore_mems(hub):
    return [m for m in hub.autobiography.all_memories(status=None)
            if getattr(m, "event_type", "") == "user_ignore"]


# ================================================================ C3-T1..T7
def test_c3_t1_scheduler_ignore_forms_memory_via_canonical_owner(tmp_path):
    """INV-C3-4：Scheduler 不得直接调用 MemoryEngine.consolidate（bypass 消失）。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    calls = []
    orig = me.consolidate
    me.consolidate = lambda exp: (calls.append(exp), orig(exp))[1]
    try:
        sched.on_user_ignore()
    finally:
        me.consolidate = orig
    assert calls == [], "Scheduler 不得直接调用 MemoryEngine.consolidate（bypass 必须消失）"
    evs = hub.events.query_by_type("USER_IGNORED")
    assert evs, "ignore 必须形成 canonical C6 USER_IGNORED 事件"
    mems = _ignore_mems(hub)
    assert mems, "ignore 应经 canonical owner（CognitionHub）形成 C3"
    for m in mems:
        assert m.source_event_ids, f"ignore C3 必须带 provenance: {m.source_event_ids}"
        assert any(e.event_id in m.source_event_ids for e in evs), \
            f"provenance 必须解析到 USER_IGNORED C6: {m.source_event_ids}"
    hub.close()


def test_c3_t2_ignore_memory_exact_source_event_ids(tmp_path):
    """INV-C3-2：形成的 memory 必须精确包含触发它的 canonical event id。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_user_ignore()
    evs = hub.events.query_by_type("USER_IGNORED")
    mems = _ignore_mems(hub)
    assert evs and mems
    assert list(mems[0].source_event_ids) == [evs[0].event_id], \
        f"exact provenance 必须等于触发事件: {mems[0].source_event_ids}"
    hub.close()


def test_c3_t3_no_provenance_less_ignore_memory(tmp_path):
    """INV-C3-2：任何 production formation path 都不得形成 source_event_ids=[] 的记忆。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_user_ignore()
    plain = [m for m in hub.autobiography.all_memories(status=None)
             if not getattr(m, "source_event_ids", None)]
    assert plain == [], f"存在无 provenance 的 durable memory: {[m.content for m in plain]}"
    hub.close()


def test_c3_t4_ignore_exactly_once_per_bid(tmp_path):
    """INV-C3-3：一次 bid 到期 → USER_IGNORED C6 恰好一次 + C3 恰好一次。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.begin_social_bid(reason="life:approach_user")
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    sched._tick_social_bid()          # 第二次 tick：bid 已清空 → 不得第二次 ignore
    evs = hub.events.query_by_type("USER_IGNORED")
    assert len(evs) == 1, f"一次到期 → 恰好一次 USER_IGNORED C6: {len(evs)}"
    assert len(_ignore_mems(hub)) == 1, "恰好一次 C3（无 duplicate）"
    hub.close()


def test_c3_t5_repo_wide_single_formation_authority():
    """INV-C3-1/INV-C3-5：静态架构审计 —— 生产代码 durable-memory 写入口唯一。

    - `consolidate` 调用点只允许 AutobiographicalMemoryStore（CognitionHub 的 delegate）；
    - `observe` 调用点只允许 CognitionHub._form_memory / AutobiographicalMemoryStore /
      App._observe_with_provenance（provenance-first 观察提交）；
    - Scheduler 不得有任何 MemoryEngine 直写。
    """

    class _CallCollector(ast.NodeVisitor):
        def __init__(self, attr):
            self.attr = attr
            self.sites = []
            self._stack = []

        def _visit_def(self, node, name):
            self._stack.append(name)
            self.generic_visit(node)
            self._stack.pop()

        def visit_FunctionDef(self, node):
            self._visit_def(node, node.name)

        def visit_AsyncFunctionDef(self, node):
            self._visit_def(node, node.name)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr == self.attr:
                self.sites.append((self._stack[-1] if self._stack else "<module>", node.lineno))
            self.generic_visit(node)

    def _sites(attr):
        out = {}
        for py in sorted((_REPO / "furina").rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            col = _CallCollector(attr)
            col.visit(tree)
            if col.sites:
                out[py.relative_to(_REPO).as_posix()] = {f for f, _ in col.sites}
        return out

    cons = _sites("consolidate")
    assert set(cons) == {"furina/cognition/stores/autobiography.py"}, \
        f"consolidate 调用点必须唯一（CognitionHub delegate）: {cons}"
    assert cons.get("furina/cognition/stores/autobiography.py", set()) <= {"consolidate"}, \
        f"delegate 必须经适配器方法转发: {cons}"

    obs = _sites("observe")
    assert "furina/runtime/scheduler.py" not in obs, "Scheduler 不得直接 observe"
    assert obs.get("furina/app.py", set()) <= {"_observe_with_provenance"}, \
        f"App 只能经 provenance-first 入口 observe: {obs}"
    assert obs.get("furina/cognition/hub.py", set()) <= {"_form_memory"}, \
        f"CognitionHub 只能经 _form_memory 形成 C3: {obs}"
    allowed_obs = {"furina/cognition/stores/autobiography.py",
                   "furina/cognition/hub.py", "furina/app.py"}
    assert set(obs) <= allowed_obs, f"存在其它 observe 写入口: {set(obs) - allowed_obs}"


def test_c3_t6_timer_without_bid_forms_nothing(tmp_path):
    """§5.3 objective semantics：没有真实 qualifying interaction 时，timer 不得凭空制造 ignore 记忆。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    for _ in range(3):
        sched._tick_social_bid(now=time.time() + 9999)
    assert hub.events.query_by_type("USER_IGNORED") == [], "无 bid → 无 USER_IGNORED C6"
    assert _ignore_mems(hub) == [], "无 bid → 无 ignore C3"
    hub.close()


def test_c3_t7_real_ignore_path_event_and_provenance(tmp_path):
    """真实 observed interaction 满足 ignore 条件 → canonical event + 正确 provenance + 唯一 owner 形成。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.begin_social_bid(reason="life:talk")
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    evs = hub.events.query_by_type("USER_IGNORED")
    assert evs and evs[0].payload.get("bid_reason") == "life:talk", \
        "USER_IGNORED 事件必须携带可观察事实（bid_reason）"
    mems = _ignore_mems(hub)
    assert mems and evs[0].event_id in mems[0].source_event_ids
    assert ("没有回应" in mems[0].content or "忽略" in mems[0].content), \
        f"记忆内容应来自客观事件（bid_reason 为观察事实）: {mems[0].content}"
    hub.close()


# ================================================================ C3-T8：objective interaction content
def test_c3_t8_poke_drag_not_recorded_as_pet_head(tmp_path):
    """互动记忆内容必须来自可观察 payload（kind/count），不得硬编码成"摸头"。

    Phase 14 R11 更新：poke/drag 使用各自独立的客观事件类型 USER_POKE / USER_DRAG
    （原 USER_PET 伞型坍缩语义被 R11 取代）。"""
    hub = _hub(tmp_path)
    hub.record_event("USER_POKE", payload={"kind": "poke", "count": 1},
                     source="interaction", importance=0.5)
    hub.record_event("USER_DRAG", payload={"kind": "drag", "count": 1},
                     source="interaction", importance=0.5)
    hub.record_event("USER_POKE", payload={"kind": "poke", "count": 9},
                     source="interaction", importance=0.5)
    contents = [m.content for m in hub.autobiography.all_memories(status=None)]
    assert any("戳" in c for c in contents), f"poke 必须记成戳: {contents}"
    assert any("拎" in c for c in contents), f"drag 必须记成拎/移动: {contents}"
    assert not any("摸" in c for c in contents), f"poke/drag 不得记成摸头: {contents}"
    hub.close()


def test_c3_t8b_interpreter_pet_kind_aware(tmp_path):
    """process_pending（interpretation）路径同样使用独立客观类型（R11）。"""
    hub = _hub(tmp_path)
    hub.events.append(event_type="USER_POKE", payload={"kind": "poke", "count": 1},
                      importance=0.6)
    hub.process_pending(batch=5)
    mems = hub.autobiography.all_memories(status=None)
    assert any("戳" in m.content for m in mems), [m.content for m in mems]
    hub.close()


# ================================================================ C4-T1..T5
def test_c4_t1_preference_supersede_trigger_provenance(tmp_path):
    """INV-C4-1：SUPERSEDED 必须知道哪个 canonical event 触发 + 为什么。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.apply_user_message("其实最近不怎么听陈奕迅了")
    rows = hub._db.query_all(
        "SELECT * FROM user_model_items WHERE category='PREFERENCE' AND status='superseded'")
    assert rows, "旧偏好必须 superseded"
    r = rows[0]
    assert r["transition_event_id"], "supersede 必须有 trigger event id"
    evs = hub.events.query_by_type("USER_PREFERENCE_CHANGED")
    assert any(e.event_id == r["transition_event_id"] for e in evs), \
        "trigger 必须可解析到 canonical C6 USER_PREFERENCE_CHANGED"
    assert r["transition_reason"] and "陈奕迅" in r["transition_reason"], \
        "supersede 必须记录触发原因（真实 utterance）"
    hub.close()


def test_c4_t2_plan_complete_trigger_provenance(tmp_path):
    """INV-C4-2：COMPLETED 必须知道哪个真实 event/utterance 证明完成。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    hub.apply_user_message("我还要写比赛报告")
    hub.apply_user_message("桌宠测试做完了")
    rows = hub._db.query_all(
        "SELECT * FROM user_model_items WHERE category='PLAN' AND status='completed'")
    assert len(rows) == 1, "只有桌宠测试被完成"
    r = rows[0]
    assert r["key"] == "plan:桌宠测试"
    assert r["transition_event_id"], "complete 必须有 trigger event id"
    evs = hub.events.query_by_type("USER_PLAN_COMPLETED")
    assert any(e.event_id == r["transition_event_id"] for e in evs), \
        "trigger 必须可解析到 canonical C6 USER_PLAN_COMPLETED"
    assert "桌宠测试" in (r["transition_reason"] or ""), "complete 必须记录触发 utterance"
    hub.close()


def test_c4_t3_ambiguous_utterance_no_transition(tmp_path):
    """INV-C4-4：含糊输入不得误 complete/supersede，也不得产生 transition 事件。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    hub.apply_user_message("我还要写比赛报告")
    hub.apply_user_message("我终于做完了")
    assert hub.events.query_by_type("USER_PLAN_COMPLETED") == [], "ambiguous → 无 transition 事件"
    assert len(hub.user_model.query_active(limit=10, category="PLAN")) == 2, \
        "两个 plan 必须仍 ACTIVE"
    hub.close()


def test_c4_t4_entity_isolation_no_cross_transition(tmp_path):
    """INV-C4-4：两个实体并存时，一个 lifecycle transition 不得污染另一个。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.apply_user_message("我喜欢咖啡")
    hub.apply_user_message("其实最近不怎么听陈奕迅了")
    rows = hub._db.query_all(
        "SELECT key,status,transition_event_id FROM user_model_items WHERE category='PREFERENCE'")
    by_key = {r["key"]: r for r in rows}
    assert by_key["preference:陈奕迅"]["status"] == "superseded"
    assert by_key["preference:咖啡"]["status"] == "active"
    assert not by_key["preference:咖啡"]["transition_event_id"], "无关实体不得被污染"
    hub.close()


def test_c4_t5_lifecycle_provenance_survives_reload(tmp_path):
    """INV-C4-3/C4-T5：provenance 是持久化数据，重载后不丢失且仍可解析。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    hub.apply_user_message("其实最近不怎么听陈奕迅了")
    hub.apply_user_message("我今天准备完成桌宠测试")
    hub.apply_user_message("桌宠测试做完了")
    hub.close()

    hub2 = _hub(tmp_path)
    rows = hub2._db.query_all(
        "SELECT * FROM user_model_items WHERE status IN ('superseded','completed')")
    assert len(rows) == 2, f"期望 1 superseded + 1 completed: {[r['key'] for r in rows]}"
    evs = hub2.events.query_recent(100)
    for r in rows:
        assert r["transition_event_id"], f"{r['key']} 的 provenance 不得丢失"
        assert any(e.event_id == r["transition_event_id"] for e in evs), \
            f"reload 后 {r['key']} 的 trigger 仍可解析到 C6"
    hub2.close()


# ================================================================ C2-T1..T5
def _canon_hub() -> CognitionHub:
    return CognitionHub(Path(tempfile.mkdtemp()) / "cog.db")


def test_c2_t1_canonical_attribution_uniqueness():
    """同一 evidence ID 在 canonical mapping 中不得产生互相矛盾的 stage/type attribution。"""
    hub = _canon_hub()
    store = hub.canon_history
    units = store.evidence_units()
    by_id = {}
    for u in units:
        assert u["evidence_id"] not in by_id, f"registry 重复 evidence_id: {u['evidence_id']}"
        by_id[u["evidence_id"]] = u
    m = store.metrics()
    assert m["evidence_attribution_conflicts"] == [], \
        f"episode 与 evidence registry 存在 act 冲突: {m['evidence_attribution_conflicts']}"
    hub.close()


def test_c2_t2_fur052_is_character_story_not_main_story():
    """FUR-052 是角色故事来源，不得被识别为 main-story（Act IV）evidence。"""
    hub = _canon_hub()
    u = hub.canon_history.evidence_unit("FUR-052")
    assert u is not None, "FUR-052 必须在 registry 中"
    assert u["source_type"] == "CHARACTER_STORY", f"FUR-052 类型错误: {u}"
    assert u.get("act") in (None, ""), "FUR-052 不得有主线 act 归属"
    hub.close()


def test_c2_t3_fur006_unique_act_one_attribution():
    """FUR-006 唯一归因：主线 Act I（Lyney 庭审）；任何 act=V 的 episode 不得引用它。"""
    hub = _canon_hub()
    u = hub.canon_history.evidence_unit("FUR-006")
    assert u is not None and u["source_type"] == "MAIN_STORY" and u["act"] == "I", u
    offenders = [e.episode_id for e in hub.canon_history.all_episodes()
                 if e.act == "V" and "FUR-006" in (e.evidence_ids or [])]
    assert offenders == [], f"FUR-006 不得再被 Act V episode 引用: {offenders}"
    hub.close()


def test_c2_t4_fur052_not_main_story_evidence_anywhere():
    """FUR-052 不得作为任何确定 act 的 main-story evidence 出现。"""
    hub = _canon_hub()
    u = hub.canon_history.evidence_unit("FUR-052")
    assert u is not None and u["source_type"] != "MAIN_STORY"
    offenders = [e.episode_id for e in hub.canon_history.all_episodes()
                 if e.act in ("I", "II", "III", "IV", "V")
                 and "FUR-052" in (e.evidence_ids or [])]
    assert offenders == [], f"FUR-052 不得作为 act 级主线证据: {offenders}"
    hub.close()


def test_c2_t5_production_reader_consistency():
    """测试读 production 真正使用的 source-of-truth（CanonHistoryStore + registry），
    而非复制测试字典。"""
    hub = _canon_hub()
    store = hub.canon_history
    reg_ids = {u["evidence_id"] for u in store.evidence_units()}
    cited = {eid for ep in store.all_episodes() for eid in (ep.evidence_ids or [])}
    missing = cited - reg_ids
    assert not missing, f"episodes 引用的 evidence 必须全部在 registry: {missing}"
    m = store.metrics()
    assert m["evidence_registry_entries"] == len(reg_ids)
    assert m["canon_span_status"] == "MANDATORY_SPAN_SOURCE_COMPLETE", m["canon_span_status"]
    assert m["dangling_source_ids"] == []
    hub.close()
