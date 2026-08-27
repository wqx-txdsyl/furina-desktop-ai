# -*- coding: utf-8 -*-
"""Phase 16A — WorkContract 数据契约测试（任务书 §6 十项最低锁定）。"""

import dataclasses
import inspect
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

from furina.agent import work_contract as wc_mod
from furina.agent.work_contract import (
    ArtifactExpectation,
    ApprovalPolicyRef,
    ContractIdConflictError,
    CostBudget,
    ExecutionBudget,
    VerificationCriterion,
    VerificationStandard,
    WorkspaceScope,
    WorkContract,
    WorkContractValidationError,
    compute_content_hash,
    ensure_no_conflict,
)

REPO_ROOT = Path(__file__).resolve().parents[3]  # 仓库根（tests/agent/integration/ 上三级）
COGNITION_TABLES = ("life_events", "agent_tasks", "agent_task_steps", "agent_artifacts")


def _minimal_kwargs(**overrides):
    kw = dict(
        contract_id="wc_test_minimal_001",
        contract_version="1.0.0",
        canonical_user_request="把 docs/notes.txt 里今天的段落整理成一份摘要文档",
        objective="在 write_root 内生成摘要文件并可通过判据校验",
        commitment_scope_included=("生成一份摘要文件",),
        allowed_capabilities=("fs.write", "fs.read"),
        allowed_backends=("native_agent",),
        workspace_scope=WorkspaceScope(
            read_roots=(str(REPO_ROOT / "docs"),),
            write_roots=(str(REPO_ROOT / "data" / "work_tmp"),),
        ),
        budget=ExecutionBudget(
            max_duration_seconds=600.0,
            cost_limit=CostBudget(amount=5.0, currency="CNY"),
            max_attempts=3,
        ),
        verification_standard=VerificationStandard(
            criteria=(
                VerificationCriterion(
                    criterion_id="summary_exists",
                    kind="artifact_file_exists",
                    params={"path": str(REPO_ROOT / "data" / "work_tmp" / "summary.md")},
                ),
            ),
        ),
        approval_policy=ApprovalPolicyRef(
            policy_id="policy_scoped_v1",
            policy_kind="pre_approved_scoped",
            scope_note="仅限 write_root 内写入",
        ),
        source_event_id="lev_1756000000000_deadbeef",
    )
    kw.update(overrides)
    return kw


def _full_contract():
    artifact_path = str(REPO_ROOT / "data" / "work_tmp" / "summary.md")
    return WorkContract(
        **_minimal_kwargs(
            contract_id="wc_test_full_002",
            commitment_scope_included=("生成摘要文件", "不改动源文件"),
            commitment_scope_excluded=("发送邮件", "删除任何既有文件"),
            artifact_expectations=(
                ArtifactExpectation(
                    artifact_id="summary_doc",
                    artifact_type="markdown_document",
                    expected_path=artifact_path,
                    required=True,
                ),
            ),
            verification_standard=VerificationStandard(
                criteria=(
                    VerificationCriterion(
                        criterion_id="summary_exists",
                        kind="artifact_file_exists",
                        params={"path": artifact_path},
                    ),
                    VerificationCriterion(
                        criterion_id="budget_zero",
                        kind="process_exit_zero",
                        params={"command": "python -m furina.checks.summary"},
                    ),
                ),
                verifier_refs=("furina.verify.phase14_dogfood_suite",),
            ),
        )
    )


# ---------------------------------------------------------------------------
# 1. 最小合法 + 完整填充契约
# ---------------------------------------------------------------------------


def test_minimal_valid_contract_constructs():
    c = WorkContract(**_minimal_kwargs())
    assert c.contract_id == "wc_test_minimal_001"
    assert len(c.content_hash) == 64
    assert int(c.content_hash, 16) >= 0


def test_fully_populated_contract_constructs():
    c = _full_contract()
    assert c.commitment_scope_excluded == ("发送邮件", "删除任何既有文件")
    assert len(c.artifact_expectations) == 1
    assert len(c.verification_standard.criteria) == 2
    assert c.verification_standard.verifier_refs == ("furina.verify.phase14_dogfood_suite",)


# ---------------------------------------------------------------------------
# 2. 确定性 ID/hash 与序列化往返；hash 排除运行时状态
# ---------------------------------------------------------------------------


def test_deterministic_hash_and_roundtrip_and_runtime_state_excluded():
    a = WorkContract(**_minimal_kwargs())
    b = WorkContract(**_minimal_kwargs(created_at_epoch=a.created_at_epoch + 999.0))
    # created_at 属运行时状态，不计入内容摘要
    assert a.content_hash == b.content_hash

    d = a.to_dict()
    rebuilt = WorkContract.from_dict(json.loads(json.dumps(d)))
    assert rebuilt == a
    assert rebuilt.content_hash == a.content_hash

    payload = {"hash_version": 1, "fields": {"x": ["b", "a"]}}
    h1 = compute_content_hash(payload)
    for _ in range(3):
        assert compute_content_hash(payload) == h1
    reordered = {"fields": {"x": ["b", "a"]}, "hash_version": 1}
    assert compute_content_hash(reordered) == h1


def test_roundtrip_detects_tampered_payload():
    a = WorkContract(**_minimal_kwargs())
    d = a.to_dict()
    d["objective"] = d["objective"] + " 被篡改"
    with pytest.raises(WorkContractValidationError, match="摘要不一致|content_hash"):
        WorkContract.from_dict(d)


# ---------------------------------------------------------------------------
# 3. 同 contract_id + 不同内容 = 冲突，而非更新
# ---------------------------------------------------------------------------


def test_same_id_different_content_is_conflict_not_update():
    base = WorkContract(**_minimal_kwargs())
    same_again = WorkContract(**_minimal_kwargs())  # 幂等重放：hash 一致
    ensure_no_conflict(base, same_again)  # 不抛

    changed = WorkContract(**_minimal_kwargs(objective="改成另一个可验证目标"))
    assert changed.contract_id == base.contract_id
    assert changed.content_hash != base.content_hash
    with pytest.raises(ContractIdConflictError):
        ensure_no_conflict(base, changed)

    other_id = WorkContract(**_minimal_kwargs(contract_id="wc_test_other_009"))
    ensure_no_conflict(base, other_id)  # 不同 id 永不冲突


# ---------------------------------------------------------------------------
# 4. 非法预算与空验收标准被拒绝
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "budget_kwargs",
    [
        {"max_duration_seconds": 0.0},
        {"max_duration_seconds": -5.0},
        {"max_duration_seconds": float("inf")},
        {"max_duration_seconds": float("nan")},
        {"max_duration_seconds": 86400 * 365 * 10},
        {"cost_limit": CostBudget(amount=0.0)},
        {"cost_limit": CostBudget(amount=-1.0)},
        {"cost_limit": CostBudget(amount=float("inf"))},
        {"max_attempts": 0},
        {"max_attempts": -1},
        {"max_attempts": 100},
    ],
)
def test_invalid_budgets_rejected(budget_kwargs):
    with pytest.raises(WorkContractValidationError):
        base_budget = ExecutionBudget(
            max_duration_seconds=600.0, cost_limit=CostBudget(amount=5.0), max_attempts=3
        )
        budget = dataclasses.replace(base_budget, **budget_kwargs)
        WorkContract(**_minimal_kwargs(budget=budget))


def test_empty_verification_standard_rejected():
    with pytest.raises(WorkContractValidationError, match="为空"):
        WorkContract(
            **_minimal_kwargs(verification_standard=VerificationStandard(criteria=(), verifier_refs=()))
        )


def test_freeform_unverifiable_criterion_kind_rejected():
    with pytest.raises(WorkContractValidationError, match="白名单"):
        WorkContract(
            **_minimal_kwargs(
                verification_standard=VerificationStandard(
                    criteria=(
                        VerificationCriterion(criterion_id="vibes", kind="looks_good_to_me", params={}),
                    ),
                )
            )
        )


# ---------------------------------------------------------------------------
# 5. 非法 / 过宽工作区被拒绝
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_roots",
    [
        ("/"),
        (str(REPO_ROOT.drive + "/") if REPO_ROOT.drive else "/"),  # 盘根 C:\ 等
        ("~"),  # 用户主目录整体
        (""),
        ("   "),
    ],
)
def test_broad_workspace_roots_rejected(bad_roots):
    with pytest.raises(WorkContractValidationError, match="过宽|空根路径"):
        WorkContract(**_minimal_kwargs(workspace_scope=WorkspaceScope(write_roots=(bad_roots,))))


def test_duplicate_workspace_roots_rejected():
    root = str(REPO_ROOT / "docs")
    with pytest.raises(WorkContractValidationError, match="重复根"):
        WorkspaceScope(read_roots=(root, root))


def test_artifact_outside_write_root_rejected(tmp_path):
    inside = tmp_path / "out.md"
    outside = str(REPO_ROOT / "docs")
    ok_scope = WorkspaceScope(read_roots=(), write_roots=(str(tmp_path),))
    with pytest.raises(WorkContractValidationError, match="write root"):
        WorkContract(
            **_minimal_kwargs(
                workspace_scope=ok_scope,
                artifact_expectations=(
                    ArtifactExpectation("doc", "file", outside, True),
                ),
                verification_standard=VerificationStandard(
                    criteria=(
                        VerificationCriterion(
                            "crit_exists", "artifact_file_exists", {"path": str(inside)}
                        ),
                    ),
                ),
            )
        )


# ---------------------------------------------------------------------------
# 6. backend 只读 projection 不可改约
# ---------------------------------------------------------------------------


def _thaw(o):
    if isinstance(o, Mapping):
        return {k: _thaw(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_thaw(v) for v in o]
    return o


def test_backend_projection_is_read_only_and_cannot_mutate_contract():
    c = _full_contract()
    proj = c.to_backend_projection()

    with pytest.raises(TypeError):
        proj["objective"] = "backend 篡改目标"  # type: ignore[index]
    with pytest.raises(TypeError):
        proj["workspace_scope"]["read_roots"] = ("/",)  # type: ignore[index]

    mutated_copy = _thaw(proj)  # 调用方自行复改：只影响自己的副本
    mutated_copy["objective"] = "backend 侧自行复改"
    mutated_copy["allowed_backends"] = ["hermes_anything"]

    # canonical 契约不受影响
    assert c.objective != "backend 侧自行复改"
    assert c.allowed_backends == ("native_agent",)
    assert c.content_hash == WorkContract.from_dict(c.to_dict()).content_hash
    assert _thaw(c.to_backend_projection()) == c.to_dict()


# ---------------------------------------------------------------------------
# 7/8. willingness、情绪、关系字段不存在；无永久布尔授权开关
# ---------------------------------------------------------------------------


def _all_field_names() -> set:
    names = set()
    for tp in (
        WorkContract,
        WorkspaceScope,
        ExecutionBudget,
        CostBudget,
        ArtifactExpectation,
        VerificationStandard,
        VerificationCriterion,
        ApprovalPolicyRef,
    ):
        names |= {f.name for f in dataclasses.fields(tp)}
    return names


WILLINGNESS_TOKENS = ("willingness", "emotion", "intimacy", "relationship", "affection", "mood")
PERMANENT_TOKENS = ("grant_permanent", "permanent", "always_allow", "approved_forever")


def test_willingness_emotion_relationship_fields_absent():
    fields = {n.lower() for n in _all_field_names()}
    for tok in WILLINGNESS_TOKENS:
        assert not any(tok in f for f in fields), f"禁止出现主观字段 token: {tok}"

    c = _full_contract()
    serialized_keys = set()
    stack = [c.to_dict()]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            serialized_keys |= {k.lower() for k in node}
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    for tok in WILLINGNESS_TOKENS:
        assert not any(tok in k for k in serialized_keys), f"序列化面出现主观字段: {tok}"


def test_no_permanent_boolean_authorization_anywhere():
    bool_fields = {
        f"{tp.__name__}.{f.name}"
        for tp in (
            WorkContract,
            ApprovalPolicyRef,
        )
        for f in dataclasses.fields(tp)
        if f.type == "bool" and any(tok in f.name.lower() for tok in PERMANENT_TOKENS)
    }
    assert bool_fields == set()

    for bad_kind in ("always_allow", "permanent_grant", "approve_forever"):
        with pytest.raises(WorkContractValidationError, match="永久|白名单"):
            ApprovalPolicyRef(policy_id="p_x", policy_kind=bad_kind)

    c = _full_contract()
    d = json.dumps(c.to_dict(), ensure_ascii=False).lower()
    for tok in PERMANENT_TOKENS:
        assert tok not in d


# ---------------------------------------------------------------------------
# 9. C1–C7 schema/行 元组前后不变
# ---------------------------------------------------------------------------


def test_c1_c7_schema_and_rows_unchanged_by_contract_construction():
    db_uri = f"file:///{(REPO_ROOT / 'furina.db').as_posix()}?mode=ro"

    def snapshot():
        con = sqlite3.connect(db_uri, uri=True)
        try:
            snap = {}
            for t in COGNITION_TABLES:
                schema_cols = tuple(
                    (r[1], r[2], r[3], r[5]) for r in con.execute(f"PRAGMA table_info({t})")
                )
                rows = tuple(con.execute(f"SELECT * FROM {t}"))
                snap[t] = (schema_cols, rows)
            return snap
        finally:
            con.close()

    before = snapshot()
    c1 = _full_contract()
    c2 = WorkContract(**_minimal_kwargs())
    ensure_no_conflict(c1, WorkContract.from_dict(c1.to_dict()))  # 幂等重放全流程
    ensure_no_conflict(c2, WorkContract(**_minimal_kwargs()))
    after = snapshot()
    assert before == after


# ---------------------------------------------------------------------------
# 10. 重启/序列化语义真实——无隐藏持久化；结构不可变
# ---------------------------------------------------------------------------


def test_restart_semantics_truthful_no_hidden_persistence_and_frozen():
    c = _full_contract()
    blob = json.dumps(c.to_dict(), ensure_ascii=False, sort_keys=True)
    revived = WorkContract.from_dict(json.loads(blob))
    assert revived == c and revived.content_hash == c.content_hash

    with pytest.raises(dataclasses.FrozenInstanceError):
        c.objective = "试图改约"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.budget.max_attempts = 99  # type: ignore[misc]

    src = inspect.getsource(wc_mod)
    for forbidden in ("sqlite3", "INSERT INTO", ".execute(", "connect(", "open(", "mkdir("):
        assert forbidden not in src, f"16A 模块不得包含持久化行为: {forbidden!r}"
