# -*- coding: utf-8 -*-
"""Phase 16A — WorkContract 数据契约测试。

任务书 §6 十项最低锁定 + Reviewer Patch 1 十个 blocker。
"""

import dataclasses
import inspect
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

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
ARTIFACT_PATH = REPO_ROOT / "data" / "work_tmp" / "summary.md"


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
                    params={"path": str(ARTIFACT_PATH)},
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


def _full_contract(**overrides):
    return WorkContract(
        **_minimal_kwargs(
            contract_id="wc_test_full_002",
            commitment_scope_included=("生成摘要文件", "不改动源文件"),
            commitment_scope_excluded=("发送邮件", "删除任何既有文件"),
            artifact_expectations=(
                ArtifactExpectation(
                    artifact_id="summary_doc",
                    artifact_type="markdown_document",
                    expected_path=str(ARTIFACT_PATH),
                    required=True,
                ),
            ),
            verification_standard=VerificationStandard(
                criteria=(
                    VerificationCriterion(
                        criterion_id="summary_exists",
                        kind="artifact_file_exists",
                        params={"path": str(ARTIFACT_PATH)},
                    ),
                    VerificationCriterion(
                        criterion_id="budget_zero",
                        kind="process_exit_zero",
                        params={"command": "python -m furina.checks.summary"},
                    ),
                ),
                verifier_refs=("furina.verify.phase14_dogfood_suite",),
            ),
            **overrides,
        )
    )


# ================================================================
# 任务书 §6.1 — 最小合法 + 完整填充
# ================================================================


def test_minimal_valid_contract_constructs():
    c = WorkContract(**_minimal_kwargs())
    assert c.contract_id == "wc_test_minimal_001"
    assert len(c.content_hash) == 64 and int(c.content_hash, 16) >= 0


def test_fully_populated_contract_constructs():
    c = _full_contract()
    assert c.commitment_scope_excluded == ("发送邮件", "删除任何既有文件")
    assert len(c.artifact_expectations) == 1
    assert len(c.verification_standard.criteria) == 2
    assert c.verification_standard.verifier_refs == ("furina.verify.phase14_dogfood_suite",)


# ================================================================
# 任务书 §6.2 + B4/B5 — 确定性 hash、严格 JSON 域、fail-closed 往返
# ================================================================


def test_deterministic_hash_and_roundtrip_and_runtime_state_excluded():
    a = WorkContract(**_minimal_kwargs())
    b = WorkContract(**_minimal_kwargs(created_at_epoch=a.created_at_epoch + 999.0))
    assert a.content_hash == b.content_hash, "created_at 属运行时状态，不得进入内容摘要"

    d = a.to_dict()
    assert WorkContract.from_dict(json.loads(json.dumps(d))) == a

    payload = {"hash_version": 1, "fields": {"x": ["b", "a"]}}
    h1 = compute_content_hash(payload)
    for _ in range(3):
        assert compute_content_hash(payload) == h1
    reordered = {"fields": {"x": ["b", "a"]}, "hash_version": 1}
    assert compute_content_hash(reordered) == h1, "键序无关"


def test_strict_json_domain_rejects_nan_inf_and_unsupported_objects():
    with pytest.raises(WorkContractValidationError, match="严格 JSON"):
        compute_content_hash({"a": float("nan")})
    with pytest.raises(WorkContractValidationError, match="严格 JSON"):
        compute_content_hash({"a": float("inf")})
    with pytest.raises(WorkContractValidationError, match="严格 JSON"):
        compute_content_hash({"a": {frozenset({1})}})  # 无 default 兜底：不支持对象直接拒绝


def test_from_dict_fail_closed_matrix():
    base = WorkContract(**_minimal_kwargs())
    good = base.to_dict()

    # marker 缺失 / 不匹配
    for marker in (None, "phase15.something.v9", ""):
        bad = dict(good)
        if marker is None:
            bad.pop("schema_marker")
        else:
            bad["schema_marker"] = marker
        with pytest.raises(WorkContractValidationError, match="schema_marker"):
            WorkContract.from_dict(bad)

    # content_hash 缺失/空/非法 —— 从不重新签名
    for mutate in (
        lambda d: d.pop("content_hash"),
        lambda d: d.update(content_hash=""),
        lambda d: d.update(content_hash=None),
        lambda d: d.update(content_hash="ABCD"),
    ):
        bad = dict(good)
        mutate(bad)
        with pytest.raises(WorkContractValidationError, match="重新签名|content_hash"):
            WorkContract.from_dict(bad)

    # 篡改后再删 hash —— 同样拒绝（exact-mapping 或 hash 层先行均视为 fail-closed）
    bad = dict(good)
    bad["objective"] = bad["objective"] + " 篡改"
    bad.pop("content_hash")
    with pytest.raises(WorkContractValidationError, match="重新签名|content_hash"):
        WorkContract.from_dict(bad)

    # 未知字段不静默丢弃
    bad = dict(good)
    bad["willingness_score"] = 0.99
    with pytest.raises(WorkContractValidationError, match="未知字段"):
        WorkContract.from_dict(bad)

    # 篡改保留旧 hash —— 摘要不符拒绝
    bad = dict(good)
    bad["objective"] = bad["objective"] + " 篡改"
    with pytest.raises(WorkContractValidationError, match="content_hash 与内容不符|篡改"):
        WorkContract.from_dict(bad)

    # 非 Mapping 输入
    with pytest.raises(WorkContractValidationError):
        WorkContract.from_dict("not-a-dict")


# ================================================================
# Patch 2 #1 — 嵌套 scalar 有损转换全部拒绝；载荷损坏不泄漏 KeyError/TypeError
# ================================================================


def test_max_attempts_bool_and_float_rejected_in_nested_transport():
    base = WorkContract(**_minimal_kwargs())
    original_hash = base.content_hash
    for bad in (True, False, 1.9, "3"):
        d = base.to_dict()
        d["budget"]["max_attempts"] = bad
        with pytest.raises(WorkContractValidationError, match="max_attempts"):
            WorkContract.from_dict(d)
    # 原 payload 未被触碰，hash 复算保持一致
    assert compute_content_hash(base._hash_payload()) == original_hash


def test_duration_numeric_string_rejected_in_nested_transport():
    base = WorkContract(**_minimal_kwargs())
    d = base.to_dict()
    d["budget"]["max_duration_seconds"] = "60.0"
    with pytest.raises(WorkContractValidationError, match="max_duration_seconds"):
        WorkContract.from_dict(d)


def test_cost_amount_and_currency_scalar_types_rejected_in_nested_transport():
    base = WorkContract(**_minimal_kwargs())
    for mutate in (
        lambda dd: dd["budget"]["cost_limit"].update(amount="5.0"),
        lambda dd: dd["budget"]["cost_limit"].update(amount=True),
        lambda dd: dd["budget"]["cost_limit"].update(currency=7),
    ):
        d = base.to_dict()
        mutate(d)
        with pytest.raises(WorkContractValidationError):
            WorkContract.from_dict(d)


@pytest.mark.parametrize(
    "path",
    [
        ("verification_standard", "criteria", 0, "criterion_id"),
        ("verification_standard", "criteria", 0, "kind"),
        ("approval_policy", "policy_id"),
        ("approval_policy", "policy_kind"),
        ("approval_policy", "scope_note"),
        ("approval_policy", "grant_record_ref"),
    ],
)
def test_valid_string_scalars_changed_to_numerics_rejected(path):
    base = WorkContract(**_minimal_kwargs())
    d = base.to_dict()
    container = d
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = 12345
    with pytest.raises(WorkContractValidationError):
        WorkContract.from_dict(d)


def _payload_fragment(name):
    """取一份合法契约的嵌套载荷片段（每次深拷贝，供缺键变异）。"""
    p = WorkContract(**_minimal_kwargs()).to_dict()
    mapping = {
        "budget": p["budget"],
        "cost": p["budget"]["cost_limit"],
        "criterion": p["verification_standard"]["criteria"][0],
        "policy": p["approval_policy"],
        "artifact": _full_contract().to_dict()["artifact_expectations"][0],
    }
    return json.loads(json.dumps(mapping[name]))


def _drop(fragment: dict, key: str) -> dict:
    fragment.pop(key)
    return fragment


@pytest.mark.parametrize(
    "name,build",
    [
        ("budget_no_cost_limit",
         lambda: ExecutionBudget.from_dict(_drop(_payload_fragment("budget"), "cost_limit"))),
        ("budget_no_duration",
         lambda: ExecutionBudget.from_dict(_drop(_payload_fragment("budget"), "max_duration_seconds"))),
        ("cost_no_amount",
         lambda: CostBudget.from_dict(_drop(_payload_fragment("cost"), "amount"))),
        ("criterion_params_wrong_shape",
         lambda: VerificationCriterion.from_dict({**_payload_fragment("criterion"), "params": [1]})),
        ("criterion_missing_id",
         lambda: VerificationCriterion.from_dict({"kind": "artifact_file_exists"})),
        ("policy_missing_kind",
         lambda: ApprovalPolicyRef.from_dict(_drop(_payload_fragment("policy"), "policy_kind"))),
        ("artifact_missing_path",
         lambda: ArtifactExpectation.from_dict(_drop(_payload_fragment("artifact"), "expected_path"))),
        ("scope_roots_not_a_sequence",
         lambda: WorkspaceScope.from_dict({"read_roots": 7, "write_roots": ()})),
    ],
)
def test_malformed_nested_payloads_raise_validation_error_not_keyerror(name, build):
    try:
        build()
    except WorkContractValidationError:
        return
    except (KeyError, TypeError, ValueError) as exc:
        pytest.fail(f"{name}.from_dict 泄漏了 {type(exc).__name__}: {exc}")
    pytest.fail(f"{name}.from_dict 未拒绝损坏载荷")


def test_direct_constructor_content_hash_format_strict():
    base = WorkContract(**_minimal_kwargs())
    # 显式提供正确 hash：合法且幂等
    assert (
        WorkContract(**_minimal_kwargs(content_hash=base.content_hash)).content_hash
        == base.content_hash
    )

    for bad in ("ABCD", "A" * 64, "a" * 63, "a" * 65, "g" * 64):
        with pytest.raises(WorkContractValidationError, match="64 位小写 hex|content_hash"):
            WorkContract(**_minimal_kwargs(content_hash=bad))

    # 格式合法但值不符 → 篡改拒绝（既有路径）
    with pytest.raises(WorkContractValidationError, match="篡改"):
        WorkContract(**_minimal_kwargs(content_hash="b" * 64))


# ================================================================
# Patch 3 — canonical schema closure：exact-mapping 键集锁定
# ================================================================

_NESTED_BUILDERS = {
    "cost": lambda frag: CostBudget.from_dict(frag),
    "workspace": lambda frag: WorkspaceScope.from_dict(frag),
    "budget": lambda frag: ExecutionBudget.from_dict(frag),
    "artifact": lambda frag: ArtifactExpectation.from_dict(frag),
    "criterion": lambda frag: VerificationCriterion.from_dict(frag),
    "standard": lambda frag: VerificationStandard.from_dict(frag),
    "policy": lambda frag: ApprovalPolicyRef.from_dict(frag),
}


def _nested_payload(kind):
    p = WorkContract(**_minimal_kwargs()).to_dict()
    full = _full_contract().to_dict()
    source = {
        "cost": p["budget"]["cost_limit"],
        "workspace": p["workspace_scope"],
        "budget": p["budget"],
        "artifact": full["artifact_expectations"][0],
        "criterion": p["verification_standard"]["criteria"][0],
        "standard": p["verification_standard"],
        "policy": p["approval_policy"],
    }
    return json.loads(json.dumps(source[kind]))


@pytest.mark.parametrize(
    "kind,bad_key",
    [
        ("budget", "unlimited"),
        ("policy", "grant_permanent"),
        ("criterion", "backend_verified"),
        ("cost", "forever_free"),
        ("workspace", "root_all"),
        ("artifact", "auto_blessed"),
        ("standard", "trust_me"),
    ],
)
def test_nested_unknown_keys_rejected_exactly(kind, bad_key):
    frag = _nested_payload(kind)
    frag[bad_key] = True
    build = _NESTED_BUILDERS[kind]
    try:
        build(frag)
    except WorkContractValidationError as exc:
        assert "未知字段" in str(exc) and bad_key in str(exc)
    except (KeyError, TypeError) as exc:
        pytest.fail(f"{kind}.from_dict 泄漏 {type(exc).__name__}: {exc}")
    else:
        pytest.fail(f"{kind}.from_dict 未拒绝未知键 {bad_key}")


@pytest.mark.parametrize(
    "kind,missing_key",
    [
        ("cost", "currency"),
        ("workspace", "read_roots"),
        ("budget", "max_attempts"),
        ("artifact", "required"),
        ("criterion", "kind"),
        ("standard", "verifier_refs"),
        ("policy", "scope_note"),
        ("policy", "grant_record_ref"),
    ],
)
def test_every_nested_mapping_missing_required_key_rejected(kind, missing_key):
    frag = _nested_payload(kind)
    del frag[missing_key]
    build = _NESTED_BUILDERS[kind]
    try:
        build(frag)
    except WorkContractValidationError as exc:
        assert "缺失必需键" in str(exc) and missing_key in str(exc)
    else:
        pytest.fail(f"{kind}.from_dict 自动补齐了 canonical 字段 {missing_key}")


@pytest.mark.parametrize(
    "dropped_field",
    ["created_at_epoch", "commitment_scope_excluded", "artifact_expectations"],
)
def test_top_level_canonical_fields_may_not_be_dropped(dropped_field):
    base = WorkContract(**_minimal_kwargs())
    d = base.to_dict()
    del d[dropped_field]
    with pytest.raises(WorkContractValidationError, match="缺失必需键"):
        WorkContract.from_dict(d)


def test_top_level_non_str_keys_rejected():
    base = WorkContract(**_minimal_kwargs())
    d = base.to_dict()
    d[7] = "int-key"
    with pytest.raises(WorkContractValidationError, match="str"):
        WorkContract.from_dict(d)


def test_params_list_of_pairs_rejected_on_both_paths():
    # 直接构造路径
    with pytest.raises(WorkContractValidationError, match="Mapping"):
        VerificationCriterion(
            criterion_id="pair_style_crit",
            kind="text_contains",
            params=[("path", "x.md"), ("needle", "y")],
        )
    # 嵌套 from_dict 路径
    frag = _nested_payload("criterion")
    frag["params"] = [["path", "x.md"], ["needle", "y"]]
    with pytest.raises(WorkContractValidationError, match="Mapping"):
        VerificationCriterion.from_dict(frag)


@pytest.mark.parametrize(
    "falsey",
    [None, False, 0, 0.0, [], {}, ()],
)
def test_falsey_non_string_content_hash_rejected_directly(falsey):
    with pytest.raises(WorkContractValidationError, match="必须是 str"):
        WorkContract(**_minimal_kwargs(content_hash=falsey))


def test_empty_string_content_hash_remains_new_creation_sentinel():
    c = WorkContract(**_minimal_kwargs(content_hash=""))
    freshly_computed = WorkContract(**_minimal_kwargs()).content_hash
    assert c.content_hash == freshly_computed


STRICT_MARKER = wc_mod.CONTRACT_SCHEMA_MARKER


def test_transport_json_duplicate_keys_rejected_including_nested():
    top_dup = '{"schema_marker":"' + STRICT_MARKER + '","schema_marker":"' + STRICT_MARKER + '"}'
    with pytest.raises(WorkContractValidationError, match="重复键"):
        WorkContract.from_transport_json(top_dup)

    nested_dup = '{"top":{"inner":1,"inner":2}}'
    with pytest.raises(WorkContractValidationError, match="重复键"):
        WorkContract.from_transport_json(nested_dup)


@pytest.mark.parametrize(
    "nonfinite",
    [
        '{"budget":{"max_duration_seconds":NaN}}',
        '{"budget":{"max_duration_seconds":Infinity}}',
        '{"budget":{"max_duration_seconds":-Infinity}}',
        '{"created_at_epoch":NaN}',
    ],
)
def test_transport_json_nan_infinity_constants_rejected(nonfinite):
    with pytest.raises(WorkContractValidationError, match="非有限常量"):
        WorkContract.from_transport_json(nonfinite)


def test_exact_schema_keys_vocabulary_exports():
    assert set(wc_mod.COST_BUDGET_KEYS) == {"amount", "currency"}
    assert set(wc_mod.WORKSPACE_SCOPE_KEYS) == {"read_roots", "write_roots"}
    assert set(wc_mod.EXECUTION_BUDGET_KEYS) == {
        "max_duration_seconds", "cost_limit", "max_attempts",
    }
    assert set(wc_mod.ARTIFACT_EXPECTATION_KEYS) == {
        "artifact_id", "artifact_type", "expected_path", "required",
    }
    assert set(wc_mod.VERIFICATION_CRITERION_KEYS) == {"criterion_id", "kind", "params"}
    assert set(wc_mod.VERIFICATION_STANDARD_KEYS) == {"criteria", "verifier_refs"}
    assert set(wc_mod.APPROVAL_POLICY_REF_KEYS) == {
        "policy_id", "policy_kind", "scope_note", "grant_record_ref",
    }
    fields = {f.name for f in dataclasses.fields(WorkContract)}
    serialized_top = set(json.loads(_full_contract().to_transport_json()).keys())
    assert serialized_top == fields | {"schema_marker"}


# ================================================================
# 任务书 §6.3 — 同 id 改约冲突
# ================================================================


def test_same_id_different_content_is_conflict_not_update():
    base = WorkContract(**_minimal_kwargs())
    ensure_no_conflict(base, WorkContract(**_minimal_kwargs()))  # 幂等重放

    changed = WorkContract(**_minimal_kwargs(objective="改成另一个可验证目标"))
    assert changed.content_hash != base.content_hash
    with pytest.raises(ContractIdConflictError):
        ensure_no_conflict(base, changed)

    ensure_no_conflict(base, WorkContract(**_minimal_kwargs(contract_id="wc_test_other_009")))


# ================================================================
# B1 — criteria defensive copy：外部 list 变更不影响契约与 hash
# ================================================================


def test_criteria_defensive_copy_external_mutation_cannot_change_hash():
    crit_list = [
        VerificationCriterion(
            criterion_id="summary_exists",
            kind="artifact_file_exists",
            params={"path": str(ARTIFACT_PATH)},
        )
    ]
    std = VerificationStandard(criteria=crit_list, verifier_refs=("furina.verify.x_suite",))
    assert isinstance(std.criteria, tuple)

    base_contract = WorkContract(**_minimal_kwargs(verification_standard=std))
    frozen_repr = repr(sorted(std.to_dict().items()))

    # 外部修改原始 list
    crit_list.append(
        VerificationCriterion(criterion_id="extra_after_fact", kind="text_contains",
                              params={"path": str(ARTIFACT_PATH), "needle": "x"})
    )
    crit_list[0] = VerificationCriterion(
        criterion_id="replaced_entry", kind="artifact_file_exists",
        params={"path": str(ARTIFACT_PATH)},
    )

    assert repr(sorted(std.to_dict().items())) == frozen_repr
    rebuilt = WorkContract.from_dict(base_contract.to_dict())
    assert rebuilt == base_contract
    # 重算 hash 始终一致
    assert compute_content_hash(base_contract._hash_payload()) == base_contract.content_hash


def test_criteria_input_list_coerced_and_frozen_immediately():
    crit_list = [VerificationCriterion("crit_a", "process_exit_zero", {"command": "true"})]
    std = VerificationStandard(criteria=crit_list)
    crit_list.clear()
    assert len(std.criteria) == 1, "构造时即固化，后续清空 list 不影响 standard"


# ================================================================
# B2/B3 — required 严格 bool；CostBudget/currency/created_at 严格验证与规范化
# ================================================================


@pytest.mark.parametrize("bad_required", ["false", "true", 0, 1, None, [], {}])
def test_artifact_required_strictly_bool(bad_required):
    with pytest.raises(WorkContractValidationError, match="严格 bool"):
        ArtifactExpectation(
            artifact_id="doc_x", artifact_type="file",
            expected_path=str(ARTIFACT_PATH), required=bad_required,
        )


def test_artifact_different_required_yields_different_hashes():
    kw = _minimal_kwargs(
        artifact_expectations=(
            ArtifactExpectation("summary_doc", "markdown_document", str(ARTIFACT_PATH), True),
        ),
    )
    h_true = WorkContract(**kw).content_hash
    kw2 = _minimal_kwargs(
        artifact_expectations=(
            ArtifactExpectation("summary_doc", "markdown_document", str(ARTIFACT_PATH), False),
        ),
    )
    h_false = WorkContract(**kw2).content_hash
    assert h_true != h_false, "不同对象内容不得产生相同 hash"


def test_from_dict_does_not_coerce_required():
    c = _full_contract()
    d = c.to_dict()
    art = d["artifact_expectations"][0]
    art["required"] = "true"  # 字符串真值禁止在往返中被转换回 True
    art_hash_original = c.content_hash
    with pytest.raises(WorkContractValidationError, match="严格 bool"):
        WorkContract.from_dict(d)
    assert c.content_hash == art_hash_original


@pytest.mark.parametrize(
    "bad_amount",
    ["5", True, False, None, 0, -1.0, float("nan"), float("inf"), float("-inf"), 2e12],
)
def test_cost_budget_amount_strict(bad_amount):
    with pytest.raises(WorkContractValidationError):
        CostBudget(amount=bad_amount, currency="CNY")


@pytest.mark.parametrize("bad_currency", ["", "   ", "dollars", "RMB!!", 123, None])
def test_cost_budget_currency_format_enforced(bad_currency):
    with pytest.raises(WorkContractValidationError):
        CostBudget(amount=1.0, currency=bad_currency)


def test_cost_budget_currency_normalized_case_insensitive_same_hash():
    a = ExecutionBudget(max_duration_seconds=60.0, cost_limit=CostBudget(1.0, "cny"), max_attempts=1)
    b = ExecutionBudget(max_duration_seconds=60.0, cost_limit=CostBudget(1.0, "CNY"), max_attempts=1)
    assert a.cost_limit.currency == "CNY" and b.cost_limit.currency == "CNY"
    c1 = WorkContract(**_minimal_kwargs(budget=a))
    c2 = WorkContract(**_minimal_kwargs(budget=b))
    assert c1.content_hash == c2.content_hash, "规范化后相同内容 → 相同 hash"


@pytest.mark.parametrize("bad_ts", ["now", True, None, [], {}, float("nan"), float("inf")])
def test_created_at_epoch_strictly_validated(bad_ts):
    with pytest.raises(WorkContractValidationError, match="created_at_epoch"):
        WorkContract(**_minimal_kwargs(created_at_epoch=bad_ts))


# ================================================================
# 任务书 §6.4 — 非法预算、空验收标准、散文判据
# ================================================================


@pytest.mark.parametrize(
    "budget_kwargs",
    [
        {"max_duration_seconds": 0.0},
        {"max_duration_seconds": -5.0},
        {"max_duration_seconds": float("inf")},
        {"max_duration_seconds": float("nan")},
        {"max_duration_seconds": 86400 * 365 * 10},
        {"cost_limit_currency": "USDX"},
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
        if "cost_limit_currency" in budget_kwargs:
            kwargs = {k: v for k, v in budget_kwargs.items() if k != "cost_limit_currency"}
            budget = dataclasses.replace(
                base_budget,
                cost_limit=CostBudget(amount=5.0, currency=budget_kwargs["cost_limit_currency"]),
                **kwargs,
            )
        else:
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
                    criteria=(VerificationCriterion(criterion_id="vibes_only", kind="looks_good_to_me",
                                                    params={}),),
                )
            )
        )


# ================================================================
# 任务书 §6.5 + B6 — 非法/过宽/非绝对工作区；sibling-prefix 安全
# ================================================================


@pytest.mark.parametrize(
    "bad_roots",
    ["/", "C:/", "C:\\\\", "~", "", "   ", "."],
)
def test_broad_or_empty_workspace_roots_rejected(bad_roots):
    with pytest.raises(WorkContractValidationError, match="过宽|非绝对|空根路径"):
        WorkContract(**_minimal_kwargs(workspace_scope=WorkspaceScope(write_roots=(bad_roots,))))


@pytest.mark.parametrize(
    "relative_root",
    ["docs", "../etc", "./docs", "work_tmp/out"],
)
def test_relative_roots_rejected_before_abspath(relative_root):
    with pytest.raises(WorkContractValidationError, match="非绝对"):
        WorkspaceScope(write_roots=(relative_root,))


def test_unc_share_root_rejected_as_too_broad():
    unc = "\\\\server\\share"
    with pytest.raises(WorkContractValidationError, match="过宽|非绝对"):
        WorkspaceScope(write_roots=(unc,))


def test_duplicate_workspace_roots_rejected():
    root = str(REPO_ROOT / "docs")
    with pytest.raises(WorkContractValidationError, match="重复根"):
        WorkspaceScope(read_roots=(root, root))


def test_sibling_prefix_paths_are_not_inside_scope(tmp_path):
    work = tmp_path / "work"
    sibling = tmp_path / "work_secret"
    scope = WorkspaceScope(read_roots=(), write_roots=(str(work),))
    assert scope.contains_path(str(work)) is True
    assert scope.contains_path(str(work / "sub" / "f.md")) is True
    assert scope.contains_path(str(sibling)) is False
    assert scope.contains_path(str(sibling / "out.txt")) is False, "sibling 前缀不得命中"


def test_artifact_outside_write_root_rejected(tmp_path):
    outside = str(REPO_ROOT / "docs")
    ok_scope = WorkspaceScope(read_roots=(), write_roots=(str(tmp_path / "out"),))
    with pytest.raises(WorkContractValidationError, match="write root"):
        WorkContract(
            **_minimal_kwargs(
                workspace_scope=ok_scope,
                artifact_expectations=(ArtifactExpectation("doc_x", "file", outside, True),),
                verification_standard=VerificationStandard(
                    criteria=(VerificationCriterion("crit_writes", "artifact_file_exists",
                                                    {"path": str(tmp_path / "out" / "o.md")}),),
                ),
            )
        )


# ================================================================
# B8 — path-based 判据必须在 read/write scope 内
# ================================================================


def test_criteria_path_outside_workspace_rejected(tmp_path):
    outside_path = str(tmp_path / "elsewhere" / "result.txt")  # 既不在 read 也不在 write
    with pytest.raises(WorkContractValidationError, match="workspace"):
        WorkContract(
            **_minimal_kwargs(
                verification_standard=VerificationStandard(
                    criteria=(
                        VerificationCriterion("crit_reads", "artifact_file_exists",
                                              {"path": outside_path}),
                    ),
                )
            )
        )


def test_criteria_path_inside_read_or_write_roots_accepted():
    read_ok = VerificationStandard(
        criteria=(VerificationCriterion("crit_reads", "artifact_file_exists",
                                        {"path": str(REPO_ROOT / "docs" / "notes.txt")}),)
    )
    write_ok = VerificationStandard(
        criteria=(VerificationCriterion("crit_writes", "artifact_file_exists",
                                        {"path": str(ARTIFACT_PATH)}),)
    )
    WorkContract(**_minimal_kwargs(verification_standard=read_ok))
    WorkContract(**_minimal_kwargs(verification_standard=write_ok))


def test_process_exit_zero_command_not_path_checked_but_params_strict():
    with pytest.raises(WorkContractValidationError, match="必须是 str"):
        VerificationCriterion(
            criterion_id="bad_param_type", kind="process_exit_zero", params={"command": 123},
        )


# ================================================================
# 任务书 §6.6 + B7 — 只读 projection 与标准 JSON transport
# ================================================================


def _thaw(o):
    if isinstance(o, Mapping):
        return {k: _thaw(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_thaw(v) for v in o]
    return o


def test_backend_projection_is_deep_readonly_and_cannot_mutate_contract():
    c = _full_contract()
    proj = c.to_backend_projection()
    assert isinstance(proj, MappingProxyType)

    with pytest.raises(TypeError):
        proj["objective"] = "backend 篡改目标"  # type: ignore[index]
    with pytest.raises(TypeError):
        proj["workspace_scope"]["read_roots"] = ("/",)  # type: ignore[index]

    mutated_copy = _thaw(proj)
    mutated_copy["objective"] = "backend 侧自行复改"
    mutated_copy["allowed_backends"] = ["hermes_anything"]

    assert c.objective != "backend 侧自行复改"
    assert c.allowed_backends == ("native_agent",)
    assert c.content_hash == WorkContract.from_dict(c.to_dict()).content_hash
    assert _thaw(proj) == c.to_dict()


def test_transport_json_roundtrip_and_no_reverse_mutation():
    c = _full_contract()
    blob = c.to_transport_json()
    loaded = json.loads(blob)
    # 往返稳定（确定性规范化顺序）
    assert json.dumps(loaded, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False) == blob
    # transport 反序列化还原同一契约
    revived = WorkContract.from_transport_json(blob)
    assert revived == c and revived.content_hash == c.content_hash

    # 反向修改 transport 载荷不影响 canonical
    loaded["objective"] = "传输面被复改"
    loaded["budget"]["max_attempts"] = 99
    assert c.objective != "传输面被复改"
    assert c.budget.max_attempts != 99
    assert c.content_hash == WorkContract.from_transport_json(c.to_transport_json()).content_hash

    # to_transport_dict 是纯 JSON plain dict（无 proxy/tuple），修改为自身副本
    td = c.to_transport_dict()

    def all_plain(x):
        if isinstance(x, dict):
            return type(x) is dict and all(all_plain(v) for v in x.values())
        if isinstance(x, list):
            return all(all_plain(v) for v in x)
        return isinstance(x, (str, int, float, bool)) or x is None

    assert all_plain(td) and td == c.to_dict()

    with pytest.raises(WorkContractValidationError, match="解析失败"):
        WorkContract.from_transport_json("{not json")


# ================================================================
# 任务书 §6.7/§6.8 — 主观字段缺失；无永久布尔授权
# ================================================================


WILLINGNESS_TOKENS = ("willingness", "emotion", "intimacy", "relationship", "affection", "mood")
PERMANENT_TOKENS = ("grant_permanent", "permanent", "always_allow", "approved_forever")


def _all_field_names() -> set:
    names = set()
    for tp in (
        WorkContract, WorkspaceScope, ExecutionBudget, CostBudget,
        ArtifactExpectation, VerificationStandard, VerificationCriterion, ApprovalPolicyRef,
    ):
        names |= {f.name for f in dataclasses.fields(tp)}
    return names


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
        assert not any(tok in k for k in serialized_keys)


def test_no_permanent_boolean_authorization_anywhere():
    bool_perm_fields = {
        f"{tp.__name__}.{f.name}"
        for tp in (WorkContract, ApprovalPolicyRef)
        for f in dataclasses.fields(tp)
        if f.type == "bool" and any(tok in f.name.lower() for tok in PERMANENT_TOKENS)
    }
    assert bool_perm_fields == set()

    for bad_kind in ("always_allow", "permanent_grant", "approve_forever"):
        with pytest.raises(WorkContractValidationError, match="永久|白名单"):
            ApprovalPolicyRef(policy_id="policy_x_v1", policy_kind=bad_kind)

    d = json.dumps(_full_contract().to_dict(), ensure_ascii=False).lower()
    for tok in PERMANENT_TOKENS:
        assert tok not in d


# ================================================================
# B9 — C1–C7 unchanged：真实 store 各自原生 truth 快照前后相等
# （Phase 15 已有真实模式：MemoryStore/MemoryEngine/CognitionHub——见
#   tests/cognition/test_phase151_truth_closure.py 的 _hub() helper）
# ================================================================

_C_LABELS = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")


class _Bus:
    def emit(self, *a, **k):
        return None


def _build_hub(tmp: Path):
    from furina.cognition import CognitionHub
    from furina.memory import MemoryEngine, MemoryStore
    from furina.relationship.engine import RelationshipEngine

    memory_store = MemoryStore(tmp / "mem.db")
    engine = MemoryEngine(_Bus(), memory_store)
    hub = CognitionHub(tmp / "cog.db", memory_engine=engine,
                       relationship_engine=RelationshipEngine())
    return hub, memory_store


def _db_snapshot(db_path: Path):
    con = sqlite3.connect(f"file:///{db_path.as_posix()}?mode=ro", uri=True)
    try:
        tables = sorted(
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        snap = {}
        for t in tables:
            schema_cols = tuple((r[1], r[2], r[3], r[5]) for r in con.execute(f"PRAGMA table_info({t})"))
            rows = tuple(con.execute(f'SELECT * FROM "{t}" ORDER BY rowid'))
            snap[t] = (schema_cols, rows)
        return snap
    finally:
        con.close()


def _canon_identity_snapshot(hub):
    ci = hub.canon_identity
    return {
        "facts": tuple(map(repr, ci.identity_facts())),
        "axes": repr(ci.personality_axes()),
        "contradictions": tuple(map(repr, ci.contradictions())),
        "anti_identity": tuple(ci.anti_identity()),
        "voice": repr(ci.voice_fingerprint()),
        "behavior": repr(ci.behavior_patterns()),
        "periods": (tuple(ci.periods()), ci.default_period()),
        "persona": ci.system_persona(),
    }


def _canon_history_snapshot(ch):
    """C2 只读 store 的公开查询面（episodes/sources/evidence 注册表）。"""
    return (
        tuple(e.episode_id for e in ch.all_episodes()),
        ch.episode_count(),
        tuple(ch.periods_covered()),
        repr(tuple(map(repr, ch.sources()))),
        repr(tuple(repr(u) for u in ch.evidence_units())),
        repr(ch.tier_counts()),
        ch.is_read_only(),
    )


def _c5_real_engine_snapshot(rel_store):
    """C5 必须取真实 RelationshipEngine 数据面（RelationshipStore 公共只读 API），
    并断言其存在——防止 getattr 兜底造成的 false-green。"""
    state = rel_store.state_dict()
    factors = rel_store.factors()
    owner = rel_store.truth_owner
    milestones = rel_store.milestones(limit=1000)
    assert owner == "RelationshipEngine", f"truth_owner 必须是 engine 本体: {owner!r}"
    assert isinstance(state, dict) and len(state) >= 5 and all(
        isinstance(v, (int, float)) for v in state.values()
    ), f"state_dict() 缺少真实引擎数值面: {state!r}"
    assert isinstance(factors, dict) and len(factors) >= 1, "factors() 不得为空"
    assert isinstance(milestones, list), "milestones() 必须返回列表"
    return {
        "owner": owner,
        "state": dict(sorted(state.items())),
        "factors": {k: float(v) for k, v in sorted(factors.items())},
        "milestones": milestones,
    }


def _native_store_snapshots(hub, tmp: Path):
    """C1–C7 逐 store 原生 truth 证据（不包含任何 Phase16 工作域概念）。"""
    cog_tables = _db_snapshot(tmp / "cog.db")
    ev = {}

    ev["C1_canon_identity"] = _canon_identity_snapshot(hub)

    # C2 — canon history / provenance 只读注册面
    ev["C2_canon_history"] = _canon_history_snapshot(hub.canon_history)

    # C3 — episodic/semantic 生产记忆库（memory engine 底层 store 全表）
    ev["C3_memory_truth_db"] = _db_snapshot(tmp / "mem.db")

    # C4 — user model lifecycle（store 原生查询面 + 底层表）
    um = hub.user_model
    ev["C4_user_model"] = (
        tuple(
            (i.item_id, i.category, i.key, i.value_json)
            for i in um.query_active(limit=1000)
        ),
        cog_tables.get("user_model_items"),
    )

    # C5 — relationship truth（store 公共只读面 → 真实 engine 数据，禁 getattr 兜底）
    rel = hub.relationship
    assert rel is not None, "hub 必须携带真实 RelationshipEngine 才能证明 C5"
    ev["C5_relationship"] = (
        _c5_real_engine_snapshot(rel),
        cog_tables.get("relationship_milestones"),
    )

    # C6 — life events append-only ledger
    estore = hub.events
    recent = tuple(
        (e.event_id, e.event_type, e.task_id, e.payload_json)
        for e in estore.query_recent(limit=5000)
    )
    ev["C6_life_events"] = (
        estore.count(),
        recent,
        cog_tables.get("life_events"),
        cog_tables.get("event_processing"),
    )

    # C7 — agent task history 三表冻结真值
    ah = hub.agent_history
    api_tasks = ()
    for attr in ("list_tasks", "all_tasks", "iter_tasks"):
        fn = getattr(ah, attr, None)
        if callable(fn):
            api_tasks = tuple(fn())
            break
    ev["C7_agent_task_history"] = (
        api_tasks,
        cog_tables.get("agent_tasks"),
        cog_tables.get("agent_task_steps"),
        cog_tables.get("agent_artifacts"),
    )

    ev["COG_DB_FULL"] = cog_tables  # 兜底：cognition 侧任何表前后一致
    return ev


def test_c1_to_c7_real_store_truth_unchanged_by_workcontract_lifecycle(tmp_path):
    hub, memory_store = _build_hub(tmp_path)
    try:
        before = _native_store_snapshots(hub, tmp_path)

        # 完整契约生命周期全流程（构造/幂等重放/冲突检测/往返/transport/projection）
        c_full = _full_contract()
        ensure_no_conflict(c_full, WorkContract.from_dict(c_full.to_dict()))
        c_min = WorkContract(**_minimal_kwargs())
        ensure_no_conflict(c_min, WorkContract.from_transport_json(c_min.to_transport_json()))
        changed = WorkContract(**_minimal_kwargs(objective="另一个可验证目标"))
        conflict_detected = False
        try:
            ensure_no_conflict(c_min, changed)
        except ContractIdConflictError:
            conflict_detected = True
        assert conflict_detected
        assert c_full.content_hash == WorkContract.from_transport_json(
            c_full.to_transport_json()
        ).content_hash

        after = _native_store_snapshots(hub, tmp_path)
    finally:
        hub.close()
        memory_store.close()

    assert before.keys() == after.keys()
    for label in before:
        assert label.startswith(_C_LABELS) or label == "COG_DB_FULL", f"必须逐 C 标注: {label}"
        assert before[label] == after[label], f"C-side truth changed: {label}"


# ================================================================
# 任务书 §6.10 + B7 措辞 — 重启真实、无隐藏持久化；结构不可变
# ================================================================


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
