# Phase 16 — 16B ExecutionBackend Protocol & Registry
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED + Reviewer Patch 1/2 已落实（等待外部验收；不声明 16B_PASS）
BASE_SHA                       = 5a0e839c77b73407a5d4701901785f28f2386db4（ACCEPTED_16A_SHA，
                                 ff-only 集成后 16B 分支起点）
                                 ceea57fc50d3d437f40830fd734fd889e77ecaa5（Patch 1 起点）
                                 c8ce379f6418f3bf7dca8531946fb6eb4e100676（Patch 2 起点）
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
                                 （ok ∧ verified）、权限行为全部原样透传；Patch 2 起
                                 Native 每次 submit 构造 task-scoped AuthorizationContext
                                 （allowed_tools=冻结快照∩契约能力，max_permission=L1，
                                 is_default=False），不伪造 16D 授权；
                                 L2（fs.organize）在默认上下文下如实 permission_denied；
                                 native “completed” 结果在 Phase 16 backend 边界仍属
                                 unverified（16F 拥有 verifier），adapter 不做二次验证
                                 也不削弱既有验证；现有 AgentRuntime 无取消面 →
                                 supports_stop=False 诚实声明）
EVENT_RESULT_REFERENCE          = BackendEvent 仅类型化引用占位（backend_id/run_id/
                                 event_type/payload），规范化与状态机由 16E 拥有；
                                 native run 结果经 last_result(run_id) 原生访问器取得
                                 （16H 拥有持久化，16E 拥有统一结果引用语义）

REVIEWER_PATCH_1                = 五项 blocker 修复：
                                 P1-1 Native 真约束 WorkContract：submit 前用 runtime 自身
                                 planner 预检每个 step——工具归属 capability 必须 ⊆ 契约
                                 allowed_capabilities（越权 capability 拒）、路径参数（复用
                                 AgentRuntime._step_paths 规范提取）必须在 workspace 内
                                 （写工具 permission≥L1 → write roots，只读 → read∪write）；
                                 工具无法归属任何 capability / 未注册 / 权限声明缺失 /
                                 契约 scope 无法解析 → BackendScopeViolation submit 前
                                 fail-closed 零执行；执行后再对实际 task_record 二次校验
                                 （LLM 偏离预检兜底；permission_denied/unknown_tool 未执行
                                 步骤跳过）。不实现 16D 异步审批：task_auth 仍为默认 L0/L1，
                                 L2/L3 依旧由 PermissionManager 默认拒绝（有测试锁定），
                                 不削弱既有权限语义。
                                 P1-2 Native 能力/健康真实：runtime 强制 isinstance
                                 AgentRuntime（假 runtime 构造即拒）；events/stop/
                                 resolve_approval 均未实现 → 一律不声明支持（supports_*=False
                                 + 能力门控拒绝测试）；workspace_scoped 仅在真正执行 scope
                                 时 true（本实现 pre+post 双校验确实执行）；capability_ids
                                 仅由 available 能力派生，无覆盖参数（杜绝虚假声明）；
                                 probe_ttl_seconds 必须有限正数（bool/0/负/NaN/Inf 全拒）。
                                 P1-3 BackendCapabilities/Health 严格校验：max_concurrent_runs
                                 type(x) is int（bool 冒充 int 拒）；max_cost_limit /
                                 max_duration_seconds 必须有限且 > 0（NaN/Inf/非正/True 拒）；
                                 health checked_at/expiry 必须有限；时序合法
                                 （checked_at ≤ expiry）；healthy=True 必须 installed ∧
                                 reachable；is_stale 改为 now ≥ expiry（到达 expiry 即
                                 stale），is_effective 改为 now < expiry。
                                 P1-4 Registry fail-closed：set_health 只接受 BackendHealth
                                 （坏健康值不得进入路由输入面）；register 校验 protocol_
                                 version == PROTOCOL_VERSION 否则类型化拒绝；descriptor /
                                 capabilities 读取包 try/except + 类型校验——坏实现不得泄漏
                                 AttributeError。
                                 P1-5 dispatch 验证 submit 返回：必须是 BackendRunHandle
                                 （None/其他 → invalid_run_handle）；handle.backend_id 必须
                                 等于选中 backend（错配 → run_handle_backend_mismatch）；
                                 非法返回均为类型化失败且零 fallback（其他 backend
                                 submit_calls==0 有测试锁定）；BackendScopeViolation 专门化
                                 failure_code=scope_violation。

REVIEWER_PATCH_2                = 三项 blocker 修复：
                                 P2-1 删除"双 planner 调用"安全模型：Native 不再做任何
                                 planner 预检（build_plan 每次 dispatch 只在
                                 AgentRuntime.execute 内发生**一次**，spy 计数锁定 ==1）；
                                 scope/capability 改在两个真实边界于每次 step 的 tool.run
                                 **之前**检查：(a) Native 专属 task-scoped
                                 AuthorizationContext（allowed_tools = 冻结快照 ∩ 契约
                                 allowed_capabilities，max_permission=L1，is_default=False）
                                 → 既有 PermissionManager 在工具边界拒绝白名单外 step
                                 （越权 capability/无归属工具 → task_scope_mismatch →
                                 permission_denied），L2/L3 因 max_permission=L1 继续拒绝
                                 （不实现 16D 异步审批，不削弱既有权限语义）；
                                 (b) AgentRuntime 新增**默认关闭**的窄 execution_guard
                                 （execute 每调用关键字参数，None 时行为与既有完全一致；
                                 并发安全——guard 为每 submit 闭包，无跨调用共享可变态，
                                 不 monkeypatch planner），在 tool.run 前做真实路径封闭。
                                 postflight 降级为**只诊断**（发现越界仅 log.warning，
                                 不作为阻止副作用的安全门——安全门由 guard 承担）。
                                 P2-2 执行层真实路径封闭：guard 用 realpath 语义解析
                                 resolved path；不存在的新文件目标按**最近现存祖先**解析
                                 后再拼回；workspace 内 symlink/junction 指向外部 →
                                 tool.run 前拒绝（写逃逸与读逃逸均拒绝，目标文件不存在
                                 有测试锁定）；新文件目标/读路径/写路径全覆盖；写工具
                                 （permission≥L1）限 write roots，只读工具限 read∪write。
                                 P2-3 冻结 capability ownership：Native 构造时建立
                                 tool→capability 不可变快照（MappingProxyType）；外部
                                 CapabilityRegistry 构造后修改不得改变既有 backend 授权
                                 （cap.injected 注入后仍 capability_mismatch，冻结快照
                                 doc.create→cap.documents 不变有测试锁定）；重复 tool
                                 owner、available 但 runtime 无对应工具 → 构造时
                                 BackendError（不一致事实 fail-closed）；能力声明只含
                                 available 且工具真实存在的能力（仅声明 AgentRuntime
                                 实际可执行的能力）。

C1_C7_SCHEMA_CHANGED           = false
DATABASE_MIGRATION_ADDED       = false
PRODUCTION_FILES_CHANGED       = 新增 furina/agent/backend/ 包（models.py/protocol.py/
                                 registry.py/router.py/native.py/__init__.py）+ 既有
                                 furina/agent/agent_runtime.py 增加默认关闭的窄
                                 execution_guard（None 时行为零变化）；其余生产文件
                                 （app.py/work_contract.py 等）零改动
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16b_execution_backend.py
TARGETED_TESTS                 = tests/agent/integration/test_phase16b_execution_backend.py：
                                 33 passed。任务书 §7 全部 12 项 + Patch 1 否证 11 项 +
                                 Patch 2 锁定 6 项：diverging planner（spy planner
                                 calls==1，guard 仍在 tool.run 前拦截越界 step，外部文件
                                 不存在）；实际 step 越权在 tool.run 前拒绝（spy tool
                                 called=False + 无归属孤儿工具 permission_denied）；
                                 symlink/junction 写逃逸与读逃逸均 tool.run 前拒绝
                                 （realpath 解析到 workspace 外；写逃逸目标文件不存在；
                                 本机 mklink /J 实测可用）；capability registry 构造后被
                                 注入 cap.injected 不影响既有 backend（能力声明不变、
                                 冻结快照不变、路由仍 capability_mismatch、既有授权照常）；
                                 合法多 root 读写正例（read root + 双 write root 均放行）；
                                 既有 L0/L1 放行、L2 denial、task_record 语义显式无回归。
AGENT_RUNTIME_REGRESSION       = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：279 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，与本
                                 阶段无关；含 AgentRuntime execution_guard 默认关闭
                                 零回归验证）
COGNITION_REGRESSION           = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变——任务书 §7.12）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q（本轮仅一次）：
                                 1524 passed, 0 failed（163.36s，exit 0）
                                 较 Patch 1 1518 恰 +6（Patch 2 新增 6 项锁定专项）

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
