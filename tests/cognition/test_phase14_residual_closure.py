"""Phase 14 Reviewer Residual Closure — reviewer-locked tests（R1–R5）。

Canonical durable-memory formation authority（可执行架构定义，Mode B）：
    Canonical durable-memory formation authority = MemoryEngine
  - formation policy（唯一）：MemoryEngine.observe 阈值 / consolidate importance 阈值 /
    _find_similar 去重 / _enforce_capacity 容量治理 —— 是否产生 durable 行由它决定；
  - persistence sink（唯一物理写入口）：MemoryStore.insert（memories 表 raw SQL 仅存在于
    memory_store.py 内部）；
  - submitters（只提交观察/事件候选，不决定持久化）：
      App._observe_with_provenance、Scheduler（仅经 CognitionHub.record_event）、
      CognitionHub._apply_*（把 consolidation 决策作为候选交给 engine API）；
  - cognitive pre-policy（提交过滤器，非平行权威）：CognitionHub Consolidator/_form_memory；
  - adapter/delegate：AutobiographicalMemoryStore（零策略转发）；
  - legacy API（存在但非独立 production authority）：MemoryEngine.consolidate（closure 后
    生产零调用）、archive/supersede（生命周期操作）、nightly_consolidate（DEV/CLI only）。

R3 canonical rule：真实合格可见 social bid 开启 → SOCIAL_BID_STARTED(E1)；到期无回应 →
USER_IGNORED(E2, payload.bid_source_event_id=E1)；memory.source_event_ids = [E2, E1]
（完整因果链，最近因果在前；无 bid 的合成语义忽略入口退化为 [E2]）。

R5 rule：direct 路径 transition 事件的 payload.statement 必须是 verbatim 原始 utterance
（终端 raw evidence，禁止 derived→derived 循环 provenance）。
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
    bus = EventBus()
    se = StateEngine(bus)
    emo = EmotionEngine(se.state.emotion)
    store = MemoryStore(tmp_path / "mem.db")
    me = MemoryEngine(_Bus(), store)
    rel = RelationshipEngine()
    hub = CognitionHub(tmp_path / "cog.db", memory_engine=me, relationship_engine=rel)
    sched = Scheduler(bus, se, None, None, me, None, None,
                      emotion_engine=emo, relationship_engine=rel, cognition=hub)
    sched.dispatcher.bind_owner()          # 生产 start() 边界（require_owner 前提）
    sched.world_perc.state.idle_available = True
    sched.world_perc.state.user_present = True
    sched.world_perc.state.user_active = True
    sched.world_perc.state.user_idle_seconds = 5.0
    sched.world_perc._has_valid_idle = True
    return sched, hub, me


def _ignore_mems(hub):
    return [m for m in hub.autobiography.all_memories(status=None)
            if getattr(m, "event_type", "") == "user_ignore"]


# ================================================================ R1 — formation authority contract
class _CallCollector(ast.NodeVisitor):
    def __init__(self, attr):
        self.attr = attr
        self.sites = []          # (enclosing_func, lineno, n_positional_args)
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
            self.sites.append((self._stack[-1] if self._stack else "<module>",
                               node.lineno, len(node.args)))
        self.generic_visit(node)


def _formation_sites(attr, *, single_arg_only=False):
    """production (furina/) 内 attr 调用点 -> {relpath: {(func, nargs)}}"""
    out: dict = {}
    for py in sorted((_REPO / "furina").rglob("*.py")):
        col = _CallCollector(attr)
        col.visit(ast.parse(py.read_text(encoding="utf-8")))
        for func, lineno, nargs in col.sites:
            if single_arg_only and nargs != 1:
                continue          # 排除 list.insert(i, x) 等双参调用
            out.setdefault(py.relative_to(_REPO).as_posix(), set()).add(func)
    return out


def test_r1_t1_formation_owner_architectural_contract():
    """R1-T1：唯一 formation authority 架构契约（AST 级，非函数名匹配）。

    自动失败于：新增第二个 production formation caller、新增直接 durable writer、
    App/Scheduler 重新取得 formation decision 权。
    """
    # formation API（observe / consolidate）调用点白名单
    obs = _formation_sites("observe")
    assert obs == {"furina/cognition/hub.py": {"_form_memory"},
                   "furina/cognition/stores/autobiography.py": {"observe"},
                   "furina/app.py": {"_observe_with_provenance"}}, \
        f"observe 调用点偏离唯一权威契约: {obs}"
    cons = _formation_sites("consolidate")
    assert cons == {"furina/cognition/stores/autobiography.py": {"consolidate"}}, \
        f"consolidate 调用点偏离唯一权威契约: {cons}"
    # Scheduler/App/Behavior 等模块不得出现在任何 formation API 调用点
    for banned in ("furina/runtime/",):
        assert not any(f.startswith(banned) for f in list(obs) + list(cons)), \
            "runtime 层不得拥有 formation decision"


def test_r1_t2_submitters_do_not_decide_formation(tmp_path):
    """R1-T2：非 owner production path 只 submit——低于 owner policy 阈值的输入
    绝不形成 durable memory；owner 接受时恰好形成且带 provenance。"""
    hub = _hub(tmp_path)
    base = hub.autobiography.count()
    # 提交者给低重要性候选 → owner policy 拒绝 → 无 durable 行
    hub.record_event("USER_PET", payload={}, source="interaction", importance=0.1)
    assert hub.autobiography.count() == base, "低于阈值的候选不得被持久化"
    # 提交者无法绕过阈值：直接 observe 低分输入同样不落库（engine 是唯一决策点）
    formed = hub.autobiography.observe("无关紧要的琐碎", importance=0.1,
                                       source_event_ids=["ev_x"])
    assert formed is None, "engine 阈值必须否决低分观察"
    # owner 接受的高分候选 → 恰好一条 + provenance
    hub.record_event("USER_PET", payload={}, source="interaction", importance=0.6)
    mems = [m for m in hub.autobiography.all_memories(status=None)]
    assert len(mems) == base + 1 and mems[-1].source_event_ids, \
        "owner 接受的形成必须带 provenance"
    hub.close()


def test_r1_t3_exact_provenance_at_owner_boundary(tmp_path):
    """R1-T3：经 owner 形成的所有 durable memory 必须 source_event_ids != [] 且可解析。"""
    hub = _hub(tmp_path)
    # ingress A：事件路径（C6 -> consolidation -> observe）
    ev_feed = hub.record_event("USER_FEED", payload={"food": "蛋糕"},
                               source="interaction", importance=0.5)
    # ingress B：观察路径（C6 statement 事件 -> observe）
    ev_stmt = hub.record_event("USER_STATEMENT_OBSERVED", payload={"text": "我喜欢喝茶"},
                               source="dialogue", importance=0.2, consolidate=False)
    m2 = hub.autobiography.observe("用户说：我喜欢喝茶", importance=0.5,
                                   source_event_ids=[ev_stmt.event_id])
    assert m2 is not None
    all_ids = set()
    for m in hub.autobiography.all_memories(status=None):
        assert m.source_event_ids, f"durable memory 无 provenance: {m.content}"
        all_ids.update(m.source_event_ids)
    evs = {e.event_id for e in hub.events.query_recent(100)}
    assert all_ids <= evs, f"provenance 必须解析到真实 C6 事件: {all_ids - evs}"
    assert ev_feed.event_id in all_ids and ev_stmt.event_id in all_ids
    hub.close()


# ================================================================ R2 — durable write sink audit
def test_r2_t1_no_direct_production_store_bypass():
    """R2-T1：production 模块不得绕过 canonical authority 直接写 memories 表。"""
    # 1) 单参 .insert()（durable write 形态；排除 list.insert 双参形态）
    inserts = _formation_sites("insert", single_arg_only=True)
    allowed_insert = {"furina/memory/memory_engine.py",
                      "furina/cognition/stores/autobiography.py",
                      "furina/cognition/hub.py"}
    assert set(inserts) <= allowed_insert, \
        f"存在 canonical authority 之外的 direct store writer: {set(inserts) - allowed_insert}"
    assert inserts.get("furina/cognition/hub.py", set()) <= {"_form_memory"}, \
        "hub 仅允许 reinforce 写回（delegate）"
    # 2) Memory(...) 构造只能在 formation authority 包内部（furina/memory/*；
    #    memory_store 的构造是 read 路径 from_row 重建）。外部构造 + insert 即为完整 bypass。
    mem_ctor = {}
    for py in sorted((_REPO / "furina").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Memory"):
                mem_ctor.setdefault(py.relative_to(_REPO).as_posix(), 0)
                mem_ctor[py.relative_to(_REPO).as_posix()] += 1
    assert set(mem_ctor) <= {"furina/memory/memory_engine.py",
                             "furina/memory/memory_store.py"}, \
        f"Memory 对象只能由 formation authority 包构造: {mem_ctor}"
    # 3) memories 表 raw SQL 只能存在于 persistence helper 内部
    offenders = []
    for py in sorted((_REPO / "furina").rglob("*.py")):
        src = py.read_text(encoding="utf-8")
        if "INSERT INTO memories" in src or "INSERT OR REPLACE INTO memories" in src:
            rel = py.relative_to(_REPO).as_posix()
            if rel != "furina/memory/memory_store.py":
                offenders.append(rel)
    assert offenders == [], f"memories 表 raw SQL 泄漏到 persistence helper 之外: {offenders}"


def test_r2_t2_legacy_cli_isolation():
    """R2-T2：migration/dev-CLI writer 不构成 normal runtime formation bypass。"""
    # nightly_consolidate 在 production 包内零调用（仅定义）
    callers = []
    for py in sorted((_REPO / "furina").rglob("*.py")):
        col = _CallCollector("nightly_consolidate")
        col.visit(ast.parse(py.read_text(encoding="utf-8")))
        if col.sites:
            callers.append(py.relative_to(_REPO).as_posix())
    assert callers == [], f"nightly_consolidate 存在 production 调用点: {callers}"
    # dev CLI 位于 scripts/（运行时包之外），且不被 furina/ 运行时代码 import
    dev_cli = _REPO / "scripts" / "dev" / "memory.py"
    assert dev_cli.is_file(), "dev memory CLI 应位于 scripts/dev/（DEV/CLI 分类）"
    for py in (_REPO / "furina").rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "import scripts" not in src and "from scripts" not in src, \
            f"运行时不得 import dev CLI: {py}"
    # autobiography.delete / engine.delete 是显式 deletion API（治理），不用于形成：
    # 其调用面已由 R2-T1 insert 白名单覆盖（delete 不是 formation）。


# ================================================================ R3 — USER_IGNORED causal provenance
def test_r3_t1_visible_bid_records_canonical_start_event(tmp_path):
    """R3：真实合格可见 social bid → canonical SOCIAL_BID_STARTED（exactly-once per bid）。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.on_mind_action_started("approach_user")     # Director 实际执行的生产回调
    evs = hub.events.query_by_type("SOCIAL_BID_STARTED")
    assert len(evs) == 1, f"合格 bid 开启必须记录恰好一次 SOCIAL_BID_STARTED: {len(evs)}"
    p = evs[0].payload
    assert p.get("reason") == "executed:approach_user" and p.get("user_present") is True
    assert sched._pending_social_bid["source_event_id"] == evs[0].event_id, \
        "pending bid 必须保存 canonical source event id"
    # 已有 pending 时再次调用 → 不重复记录（exactly-once）
    sched.begin_social_bid(reason="spoken:talk")
    assert len(hub.events.query_by_type("SOCIAL_BID_STARTED")) == 1
    hub.close()


def test_r3_t2_user_ignored_references_bid_source_event(tmp_path):
    """R3：USER_IGNORED 的因果溯源指向触发它的 SOCIAL_BID_STARTED 事件 id。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.begin_social_bid(reason="spoken:talk")
    e1 = hub.events.query_by_type("SOCIAL_BID_STARTED")[0]
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    ignored = hub.events.query_by_type("USER_IGNORED")
    assert len(ignored) == 1
    assert ignored[0].payload.get("bid_source_event_id") == e1.event_id, \
        f"USER_IGNORED 必须引用真实 bid 事件: {ignored[0].payload}"
    hub.close()


def test_r3_t3_unknown_presence_no_bid_event_no_ignore(tmp_path):
    """R3：unknown/absent presence → 无 bid、无 SOCIAL_BID_STARTED、无 ignore。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    sched.world_perc.state.idle_available = False       # known=False
    sched.begin_social_bid(reason="spoken:talk")
    assert sched._pending_social_bid is None
    assert hub.events.query_by_type("SOCIAL_BID_STARTED") == []
    sched._tick_social_bid(now=time.time() + 9999)
    assert hub.events.query_by_type("USER_IGNORED") == []
    hub.close()


def test_r3_t4_suppressed_or_failed_speech_no_bid(tmp_path):
    """R3：ambient 被抑制（direct active）/ 台词失败 → 无 bid、无起始事件。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    # a) suppressed channel：direct turn active → AMBIENT EPHEMERAL 同步 drop（无线程）
    sched.dialogue_brain = type("_DB", (), {"say": lambda **k: "嗯。"})()
    sched._active_direct_turns.add(1)
    sched.start_autonomous_dialogue(activity="talk")
    assert sched._pending_social_bid is None
    assert hub.events.query_by_type("SOCIAL_BID_STARTED") == []
    # b) speech failed：worker 出话失败 → 不开 bid
    sched2, hub2, _ = _sched_with_cog(tmp_path)

    class _FailBrain:
        called = False
        def say(self, **k):
            type(self).called = True
            return ""
    fb = _FailBrain()
    sched2.dialogue_brain = fb
    sched2.start_autonomous_dialogue(activity="greet")
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not fb.called:
        time.sleep(0.02)
    assert fb.called, "worker 应已尝试出话"
    assert sched2._pending_social_bid is None, "台词失败不得开启响应窗口"
    assert hub2.events.query_by_type("SOCIAL_BID_STARTED") == []
    hub.close()
    hub2.close()


# ================================================================ R4 — C3-T7 real ignore end-to-end
def test_c3_t7_real_ignore_end_to_end_production_path(tmp_path):
    """C3-T7：真实生产路径端到端 —— Director 执行社交动作 → 可见 bid → canonical 起始事件
    → 到期无回应 → medium tick → USER_IGNORED → cognition → durable memory（完整因果链）
    + exactly-once。"""
    sched, hub, me = _sched_with_cog(tmp_path)
    # 1) eligible social action 经 Director 真正执行（app._on_execute 的生产回调）
    sched.on_mind_action_started("approach_user")
    bids = hub.events.query_by_type("SOCIAL_BID_STARTED")
    assert len(bids) == 1
    e1 = bids[0]
    # 2) 无回应 → 窗口到期 → medium tick（生产入口）
    sched._pending_social_bid["deadline"] = time.time() - 1.0
    sched._tick_social_bid()
    # 3) Event layer：各恰好一次
    ignored = hub.events.query_by_type("USER_IGNORED")
    assert len(hub.events.query_by_type("SOCIAL_BID_STARTED")) == 1
    assert len(ignored) == 1
    e2 = ignored[0]
    # 4) Provenance：USER_IGNORED 引用真实 bid 事件
    assert e2.payload.get("bid_source_event_id") == e1.event_id
    # 5) Memory：canonical 因果链规则 [USER_IGNORED, SOCIAL_BID_STARTED]
    mems = _ignore_mems(hub)
    assert len(mems) == 1
    assert list(mems[0].source_event_ids) == [e2.event_id, e1.event_id], \
        f"memory 必须携带完整因果链: {mems[0].source_event_ids}"
    # 6) Exactly-once：再 tick 不重复
    sched._tick_social_bid()
    assert len(hub.events.query_by_type("USER_IGNORED")) == 1
    assert len(_ignore_mems(hub)) == 1
    hub.close()


def test_c3_t7_negative_counterfactuals(tmp_path):
    """C3-T7 negatives：responds / no-bid 场景不得产生 USER_IGNORED 或记忆。"""
    # a) user responds → bid 取消 → 无 ignore（SOCIAL_BID_STARTED 作为客观事实保留）
    s1, h1, _ = _sched_with_cog(tmp_path / "a")
    s1.on_mind_action_started("approach_user")
    s1.on_user_response()
    s1._tick_social_bid(now=time.time() + 9999)
    assert len(h1.events.query_by_type("SOCIAL_BID_STARTED")) == 1   # bid 客观发生过
    assert h1.events.query_by_type("USER_IGNORED") == []
    assert _ignore_mems(h1) == []
    h1.close()
    # b) no bid at all → tick 永远不制造 ignore（独立 DB，隔离 a 的历史）
    s2, h2, _ = _sched_with_cog(tmp_path / "b")
    s2._tick_social_bid(now=time.time() + 9999)
    assert h2.events.query_by_type("SOCIAL_BID_STARTED") == []
    assert h2.events.query_by_type("USER_IGNORED") == []
    assert _ignore_mems(h2) == []
    h2.close()


# ================================================================ R5 — original utterance provenance
def test_r5_t1_preference_transition_resolves_to_original_utterance(tmp_path):
    """R5-T1：从 DB row 的 transition_event_id 出发真实 resolve 到 verbatim 原始话语。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    utt = "其实最近不怎么听陈奕迅了"
    hub.apply_user_message(utt)
    row = hub._db.query_one(
        "SELECT * FROM user_model_items WHERE category='PREFERENCE' AND status='superseded'")
    assert row and row["transition_event_id"]
    ev = hub.events.query_recent(100)
    target = next(e for e in ev if e.event_id == row["transition_event_id"])
    assert target.event_type == "USER_PREFERENCE_CHANGED"
    # 终端 raw evidence：payload.statement == 原始 utterance（verbatim）
    assert target.payload.get("statement") == utt, \
        f"transition 事件必须携带 verbatim 原始话语: {target.payload}"
    assert row["transition_reason"] == utt
    hub.close()


def test_r5_t2_plan_complete_resolves_to_original_utterance(tmp_path):
    """R5-T2：plan complete 的 transition 同样回溯到原始话语。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我今天准备完成桌宠测试")
    utt = "桌宠测试做完了"
    hub.apply_user_message(utt)
    row = hub._db.query_one(
        "SELECT * FROM user_model_items WHERE category='PLAN' AND status='completed'")
    assert row and row["transition_event_id"]
    ev = next(e for e in hub.events.query_recent(100)
              if e.event_id == row["transition_event_id"])
    assert ev.event_type == "USER_PLAN_COMPLETED"
    assert ev.payload.get("statement") == utt
    assert row["transition_reason"] == utt
    hub.close()


def test_r5_t3_no_circular_provenance(tmp_path):
    """R5-T3：禁止 transition row → derived event → transition row 的循环唯一证据。"""
    hub = _hub(tmp_path)
    hub.apply_user_message("我喜欢陈奕迅")
    utt = "其实最近不怎么听陈奕迅了"
    hub.apply_user_message(utt)
    row = hub._db.query_one(
        "SELECT * FROM user_model_items WHERE category='PREFERENCE' AND status='superseded'")
    ev = next(e for e in hub.events.query_recent(100)
              if e.event_id == row["transition_event_id"])
    # 证据链终止于 raw 文本（一跳内），不是指回 lifecycle row 的指针
    stmt = ev.payload.get("statement", "")
    assert isinstance(stmt, str) and stmt == utt and stmt.strip() != ""
    assert ev.event_id != row["item_id"], "derived event 不得与 lifecycle row 同 identity"
    # derived event 自身没有引用自己的 provenance（无循环边）
    cited = set(ev.payload.keys())
    assert "transition_event_id" not in cited and "source_event_id" not in cited
    hub.close()


def test_r5_t4_production_turn_links_transition_to_canonical_utterance(tmp_path):
    """R5（production ingress）：真实 submit_user_message 路径下，transition 事件的
    verbatim utterance 与 EventBridge 的 canonical USER_MESSAGE 事件文本一致 ——
    derived semantic event 可双向对齐到 canonical utterance event。"""
    from PySide6.QtWidgets import QApplication
    from furina.app import Furina
    from furina.config import AppConfig, LLMProfile
    QApplication.instance() or QApplication([])
    cfg = AppConfig(root_dir=tmp_path, zhipu_api_key="", agnes_api_key="",
                    llm=LLMProfile(api_key=""), data_dir=tmp_path)
    f = Furina(cfg)
    try:
        f._rt_dispatcher().bind_owner()
        f.dialogue_brain = type("_Stub", (), {"say_with_result": lambda self, **k: {
            "speech": "", "failure_reason": "stub", "validation_issues": [],
            "hard_issues": [], "soft_issues": []}})()
        f.submit_user_message("我喜欢喝咖啡")
        utt = "我现在不喝咖啡了"
        f.submit_user_message(utt)
        changed = f.cognition.events.query_by_type("USER_PREFERENCE_CHANGED")
        assert changed, "真实 turn 必须产生 transition 事件"
        assert changed[0].payload.get("statement") == utt, \
            f"transition 事件必须携带 verbatim utterance: {changed[0].payload}"
        # 与 bridge 的 canonical USER_MESSAGE 事件交叉对齐（同一原始话语）
        umsg = [e for e in f.cognition.events.query_by_type("USER_MESSAGE")
                if e.payload.get("text") == utt]
        assert umsg, "canonical USER_MESSAGE（utterance event）必须存在且文本一致"
        row = f.cognition._db.query_one(
            "SELECT * FROM user_model_items WHERE category='PREFERENCE' "
            "AND status='superseded'")
        assert row and row["transition_event_id"] == changed[0].event_id
    finally:
        try:
            if f.cognition is not None:
                f.cognition.close()
        except Exception:
            pass
