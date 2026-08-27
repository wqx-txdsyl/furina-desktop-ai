# Phase 16 — 16B ExecutionBackend Protocol & Registry
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（等待外部验收；不声明 16B_PASS）
BASE_SHA                       = 5a0e839c77b73407a5d4701901785f28f2386db4（ACCEPTED_16A_SHA，
                                 ff-only 集成后 16B 分支起点）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A 惯例）
BRANCH                         = feature/phase16-16b-execution-backend
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

BACKEND_PROTOCOL_MODULE        = furina/agent/backend/protocol.py（ExecutionBackend ABC：
                                 probe/submit/events/stop + 可选 resolve_approval；
                                 可选能力一律显式布尔门控，未声明即抛
                                 BackendCapabilityError——fail-closed，绝不在未声明
                                 能力上假装工作）
REGISTRY_MODULE                = furina/agent/backend/registry.py（ExecutionBackendRegistry：
                                 显式 register、同 id 二次注册拒绝、get/get_required/
                                 list_ids/snapshot；健康事实由 registry 显式建立
                                 （probe/set_health）并只读缓存——路由不现场探测；
                                 无 install/uninstall/upgrade/remove 任何方法）
TECHNICAL_ROUTER_MODULE        = furina/agent/backend/router.py（TechnicalRouter +
                                 RoutingPolicy + RouteDecision + DispatchResult；
                                 route 仅接受 WorkContract 一个输入面）
NATIVE_ADAPTER_MODULE          = furina/agent/backend/native.py（NativeAgentRuntimeBackend：
                                 薄包装 AgentRuntime.execute，语义原样透传）
INSTALLED_HEALTHY_SEPARATED    = true（BackendHealth 四态严格分离 installed/reachable/
                                 healthy + checked_at/expiry；is_effective =
                                 installed ∧ reachable ∧ healthy ∧ 未过期；注册 ≠ 执行：
                                 注册不建立健康事实，未 probe 的 backend 由 router
                                 fail-closed 拒绝（refusal 原因 not_probed））
CAPABILITY_MATCH_FAIL_CLOSED   = true（contract.allowed_capabilities 必须是 backend
                                 BackendCapabilities.capability_ids 的显式子集，否则
                                 capability_mismatch 拒绝；能力声明只允许有限集合 +
                                 布尔 + 数值上限，无 free-form 承诺）
ROUTING_DETERMINISTIC          = true（路由仅用任务书 §4 六类输入：契约 allowed_backends
                                 显式约束、允许 backend 集合（系统级只收窄不放宽）、必需
                                 能力、当前非过期健康、workspace/budget 兼容（显式上限 +
                                 workspace_scoped）、策略配置的确定性 tie-break
                                 （preferred 顺序 + backend_id 字典序兜底）；候选顺序与
                                 结果多次路由完全一致有测试锁定）
AGENCY_INPUTS_USED             = false（route() 签名只接受 contract；Persona/情绪/关系/
                                 willingness/intimacy 字段不存在于任何路由输入；测试
                                 9…对应 §7.7：persona 化请求文本与中性文本路由结果一致，
                                 且 inspect.signature 断言无额外参数）
INSTALL_UNINSTALL_IMPLEMENTED  = false（registry 无 install/uninstall/upgrade/remove；
                                 注册零副作用——不 probe 不 submit，测试锁定）
MCP_BACKEND_IMPLEMENTED        = false
NO_SILENT_FALLBACK             = true（dispatch 先 route：拒绝 → 类型化 refusal 零 submit；
                                 submit 抛异常 → fail-soft 类型化失败
                                 （failure_code=submit_error），绝不静默换到另一个
                                 backend，测试锁定被跳过 backend submit_calls==0）
NATIVE_SEMANTICS_PRESERVED     = true（任务记录 task_record、ToolResult 验证
                                 （ok ∧ verified）、权限行为全部原样透传；task_auth=None
                                 → AgentRuntime 默认 L0/L1 任务上下文，不伪造 16D 授权；
                                 L2（fs.organize）在默认上下文下如实 permission_denied；
                                 native “completed” 结果在 Phase 16 backend 边界仍属
                                 unverified（16F 拥有 verifier），adapter 不做二次验证
                                 也不削弱既有验证；现有 AgentRuntime 无取消面 →
                                 supports_stop=False 诚实声明）
EVENT_RESULT_REFERENCE          = BackendEvent 仅类型化引用占位（backend_id/run_id/
                                 event_type/payload），规范化与状态机由 16E 拥有；
                                 native run 结果经 last_result(run_id) 原生访问器取得
                                 （16H 拥有持久化，16E 拥有统一结果引用语义）

C1_C7_SCHEMA_CHANGED           = false
DATABASE_MIGRATION_ADDED       = false
PRODUCTION_FILES_CHANGED       = 仅新增 furina/agent/backend/ 包（models.py/protocol.py/
                                 registry.py/router.py/native.py/__init__.py）；
                                 未修改任何既有生产文件（app.py/agent_runtime.py/
                                 work_contract.py 等零改动）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16b_execution_backend.py
TARGETED_TESTS                 = tests/agent/integration/test_phase16b_execution_backend.py：
                                 16 passed。覆盖任务书 §7 全部 12 项：1 重复 id 拒绝
                                 （同 id 不同实例/同实例/非 ExecutionBackend 三路径）；
                                 2 installed-but-unhealthy 不可路由 + 未 probe 的已注册
                                 backend fail-closed（not_probed）；3 stale health
                                 （expiry 已过）不得当作 healthy；4 能力不匹配 → 零 submit；
                                 5 显式 allowed_backends 不可被策略偏好/允许集放宽（契约外
                                 健康 backend 也绝不落入）；6 确定性 tie-break 可重复
                                 （偏好顺序 + 字典序兜底 + 候选顺序锁定）；7 persona/
                                 relationship 不影响技术路由（路由输入面结构断言）；
                                 8 submit 异常 → fail-soft 类型化失败且不静默 fallback；
                                 9 Native adapter 保留既有结果语义（COMPLETED_VERIFIED +
                                 verified + 真实文件 + task_record 回调原样；9b 权限语义
                                 permission_denied 不被削弱 + 能力门控 events/stop/
                                 resolve_approval 全拒）；10 registry snapshot
                                 不可变/调用方安全（MappingProxyType + 副本解耦 +
                                 后续注册不影响旧快照）；11 无安装/卸载（方法面断言 +
                                 注册零副作用）+ 11b 导入 backend 包不拉入 furina.cognition
                                 （subprocess 干净解释器守卫）；另有拒绝码类型化
                                 （no_registered_backend/no_compatible_backend）、预算/
                                 workspace 不兼容否决等专项。
AGENT_RUNTIME_REGRESSION       = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：262 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，与本
                                 阶段无关）
COGNITION_REGRESSION           = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变——任务书 §7.12）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q（本轮仅一次）：
                                 1507 passed, 0 failed（190.07s，exit 0）
                                 较集成基线 1491 恰 +16（新增 16B 专项）

REMAINING_GAPS                 = 1) 按 brief 无 Hermes(16C)/approval channel(16D)/事件
                                   状态机(16E)/verifier(16F)/持久化 ledger(16H)/C7
                                   commit(16G)/MCP/安装卸载——全部留待对应子阶段；
                                   2) Native backend 未接入 App 生产 wiring（本阶段仅
                                   模块 + conformance 测试；消费接线属后续子阶段）；
                                   3) BackendEvent 仅为类型化引用占位，规范化语义由
                                   16E 定义；4) 健康探测 TTL 为模块级参数，无全局策略
                                   持久化；5) 基线已有 untracked（data/assets_v2/、
                                   scripts/assets_v2/、_night_*、nul）保持未触碰
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16B_PASS`.
