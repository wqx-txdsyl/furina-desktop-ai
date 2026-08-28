# Phase 16 — 16E Backend Event Normalization
# Closeout Report — EXACT TEMPLATE

```text
STATUS                         = EXECUTED（Reviewer Patch 5 修复完成 + 全量测试通过，
                                 等待外部验收；不声明 16E_PASS）
BASE_SHA                       = 521dc5a990a2f6b62c9f0d9c1107fe14dcf553e1
                                 （Reviewer Patch 4 FINAL_SHA；Patch 5 以此为基；
                                 Patch 3 基线 73f601a… / Patch 2 基线 a691b59… /
                                 初版基线 7658ab30… 见 REVIEWER_PATCH_1/2/3/4 记录）
FINAL_SHA                      = 见外部 handoff（closeout 不包含自身 commit SHA，沿用 16A/16B/16D 惯例）
BRANCH                         = feature/phase16-16e-event-normalization
LOCAL_REMOTE_MATCH             = push 后核验，结论记录于外部 handoff

REVIEWER_PATCH_5               = 3 组 micro-blocker 全部修复并逐一否证锁定（test_patch5a–5e）：
                                 1) 嵌入字符串秘密值完整脱敏（models.py 秘密值正则
                                    重写）：值支持 **1 字符及以上**（password=x /
                                    password=ab / token=短）、**Unicode**（password=
                                    秘密）、**常见特殊字符**（p@ss / abc@def）；
                                    **quoted 值由值自身携带配对引号**（覆盖到闭合
                                    引号：password="a b" / {"access_token":"x"}）；
                                    **unquoted 值至少覆盖到空白/行结束/明确结构
                                    分隔符**（排除集：空白、引号、{}[]()、;,——值内
                                    含 = / @ / Unicode 一律整段覆盖，**绝不只替换
                                    前缀残留后缀**：password=abc@def 不得残留 @def）；
                                    `[` 排除同时保证已插入的 [REDACTED] 标记不会被
                                    二次匹配；**任一真实替换必须令 lossy_payload
                                    =true**；导出面（payload/to_dict/repr/event_id/
                                    diagnostic）无原始秘密；**负向对照零误杀**
                                    （token_count=5 / author=alice / ordinary
                                    message 保持原文且 lossy=false）；structured
                                    secret key（dict 键）脱敏能力无回归；
                                 2) tuple/list 类型擦除（选择方案 A）：tuple→list
                                    保持现有输出形态，但 **tuple 路径一律
                                    lossy_payload=true**（raw 无法唯一复原：(1,) 与
                                    [1] 清洗后同形）；list JSON payload 保持
                                    lossy=false；**同 event_id 的 list/tuple 不得被
                                    静默判 duplicate_event**——任一侧 lossy 时保守
                                    event_id_ambiguous 零变更（list→tuple 与
                                    tuple→list 双向均有否证）；fresh replay 结果
                                    确定；
                                 3) 静态清理：reducer.py:422 行尾空格删除，git
                                    diff --check 为空、exit 0
                                 适配：既有 48 项测试全数保留零改动全过，新增 5 项
                                 reviewer-locked 否证（test_patch5a–5e），专项 53

REVIEWER_PATCH_4               = 3 组 blocker 全部修复并逐一否证锁定（test_patch4a–4f）：
                                 1) fallback event_id 不得依赖原始敏感 payload：
                                    _derive_event_id 改为只由 backend/run 身份、
                                    canonical kind、sequence 与独立递增的 arrival
                                    ordinal 派生——**绝不包含/散列/派生自 raw
                                    payload**（password AAA vs BBB 在同一位置 →
                                    fallback ID 完全一致；同一 normalizer 连续两个
                                    相同事件因 arrival 不同而 ID 不同；完整输入流
                                    重放确定；event_id 摘要结构证明只含非敏感字段；
                                    event_id/to_dict/provenance 中不存在原始秘密或
                                    其可公开枚举的普通摘要）；显式上游 event_id
                                    行为不变；删除"内容寻址"这一不再准确的文档措辞
                                    （normalizer/reducer/测试/closeout 全部更新）；
                                 2) lossy sanitization 身份碰撞修复（选择保守方案
                                    A）：payload 清洗是否丢失/改写了任何原始信息
                                    （秘密键脱敏、秘密值形态、第 256 字符后截断、
                                    整体超预算截断、深度/非法值丢弃、控制字符替换、
                                    bytes 解码类型擦除）由信封 lossy_payload 布尔
                                    判据明确携带（**只保存布尔判据，绝不保存/导出
                                    raw secret 或其普通未加密摘要，不使用 keyed
                                    discriminator——不破坏 fresh normalizer/reducer
                                    重放确定性**）；event_id 去重与 approval request
                                    幂等对 lossy 内容保守返回 typed ambiguous
                                    （event_id_ambiguous / approval_request_ambiguous，
                                    零状态变更、绝不覆盖 pending）：同 approval_id
                                    的 password AAA→BBB、仅第 257 字符不同都不得
                                    判定幂等；同 event_id 不同 secret-bearing
                                    payload 不得返回 duplicate_event；完全相同、
                                    非 lossy payload 重投仍保持现有幂等；失败后
                                    pending 不被覆盖、仍可由原 approval_id resolve；
                                    不伪造 16D operation_digest、16E 非授权 owner；
                                 3) 工具身份 lexical contract：tool/tool_name/name/
                                    toolId 所有别名 strip 后必须规范化一致，且以
                                    字母/数字开头、仅含 [A-Za-z0-9._:-]、总长
                                    <=128——内部空白（control-char 经 sanitizer 变为
                                    空格后同样词法非法）、斜杠、下划线开头及其它
                                    非法字符一律 tool_identity_invalid
                                    （TOOL_STARTED/显式 TOOL_PROGRESS/
                                    TOOL_COMPLETED 共用同一规则）；app.launch/
                                    browser.open/fs.read_file/fs.write_text/
                                    doc.create/comm.send_message 正样本通过；
                                    generic message.delta/reasoning 无工具身份仍为
                                    合法 self-loop（无回归）；非法事件失败后
                                    tool_subphase/active_tool/processed_count 不变
                                 适配：既有 42 项测试全数保留零改动，新增 6 项
                                 reviewer-locked 否证（test_patch4a–4f），专项 48

REVIEWER_PATCH_3               = 4 组 blocker 全部修复并逐一否证锁定（test_patch3a–3i）：
                                 1) NormalizedEvent 真正 API-immutable（构造完成后
                                    普通赋值/删除任何内部字段（_kind/_backend_id/
                                    _payload/_terminal/_sequence/… 全部 12 slots 与
                                    公共属性）一律 AttributeError、原值不变；构造 /
                                    to_dict / payload freeze / terminal+critical
                                    派生语义保持不变；不把 Python immutability
                                    宣称为进程安全边界）；
                                 2) Approval 语义精确：
                                    a) approval_id 明确 lexical contract（以字母/
                                       数字开头、仅含 [A-Za-z0-9._:-]、总长 <=128）
                                       ——内部空白/control-char 经 sanitizer 变成
                                       空格后同样词法非法拒绝（"ap\x00bad" 清洗为
                                       "ap bad" → approval_id_invalid），不接受
                                       内部空白/截断/别名冲突；
                                    b) outcome 别名一致性：outcome/decision/
                                       resolution/result 所有已出现别名必须规范化
                                       一致（approve≈approved≈allow≈granted 等价）；
                                       approve 与 deny/timeout 冲突 →
                                       outcome_conflict typed rejection 零状态变化
                                       （pending 保留可重试）；非 str/空/未知值
                                       fail-closed；verification outcome 别名同样
                                       一致性检查（start vs failed 冲突拒绝），
                                       避免相邻 first-key-wins；
                                    c) pending request 除 approval_id 外保存
                                       canonical sanitized request fingerprint——
                                       WAITING 中只有『同 approval_id + 同请求
                                       内容』才是幂等观察；同 id 但 tool/scope/args/
                                       其它 payload 不同 → approval_request_conflict
                                       零变更、不得覆盖 pending；resolution 后同时
                                       清除 pending id 与 fingerprint；
                                 3) TOOL_PROGRESS 语义精确化（取代 Patch 2 的
                                    "tick 也必须归因"）：payload 显式携带 tool
                                    identity 时必须与 active_tool 精确匹配（不同/
                                    类型非法/别名冲突均 typed rejection 零变更）；
                                    payload 未携带任何工具身份时作为 generic
                                    stream/progress tick——RUNNING 中合法
                                    self-loop，不建立/不关闭/不改变 tool_subphase；
                                    message.delta/reasoning/reasoning.delta 无
                                    tool 字段的真实 fixture 必须通过 reducer 且
                                    永远不能产生终态或 VERIFIED；TOOL_STARTED/
                                    TOOL_COMPLETED 仍必须有合法且匹配的工具身份
                                    （生命周期配对不放宽）；背压分类保持
                                    （TOOL_PROGRESS droppable；TOOL_STARTED/
                                    COMPLETED critical）；
                                 4) Typed BackendEvent payload exactness：payload
                                    None = 合法空 payload、Mapping = 正常归一；
                                    list/str/int/任意对象等非 Mapping 显式载荷一律
                                    EventNormalizationError——不静默替换为 {}
                                    （信封构造与 sanitize_payload 双入口同样
                                    fail-closed）
                                 适配：既有 33 项测试全数保留，仅 test_patch2e 中
                                 『TOOL_PROGRESS 缺身份 → 拒绝』一条断言按 Patch 3
                                 新语义适配为『无身份 → generic tick 合法 self-loop』
                                 （该断言与 Patch 3 强制语义直接冲突，属必然语义
                                 更新），其余 32 项零改动全过；新增 9 项
                                 reviewer-locked 否证（test_patch3a–3i），专项 42

REVIEWER_PATCH_2               = 5 项 blocker 全部修复并逐一否证锁定（test_patch2a–2e）：
                                 1) Mapping 别名无歧义（身份字段 backend_id/backendId、
                                    contract_id/contractId、run_id/runId 所有已出现
                                    别名逐一校验等于绑定值，不得检查第一个后 break；
                                    event_id/eventId/id、sequence/seq/number、时间、
                                    kind/status 多别名同时出现等值允许、冲突值拒绝；
                                    显式出现但类型/范围非法的 event_id/sequence/
                                    timestamp/payload 不得当作缺失自动补值）；
                                 2) fallback event_id 每次到达唯一（独立 arrival
                                    ordinal 递增，派生 id 纳入 arrival——显式 sequence
                                    后接缺 sequence、重复显式 sequence、混合流均不得
                                    碰撞；fresh normalizer 重放同一输入流确定性一致；
                                    只有上游稳定 event_id 才声明强重投幂等）；
                                 3) max_payload_bytes 是真实 UTF-8 byte 上限
                                    （len(encoded.encode("utf-8"))；truncation marker
                                    自身也不超预算——最小预算 128B fail-closed，不允许
                                    声称允许 1 byte 却返回超预算 JSON；original_bytes
                                    记录真实 UTF-8 bytes）；
                                 4) approval_id 精确绑定（禁止 [:128] 静默截断，非法/
                                    超长/control-char/别名冲突 ID 直接 approval_id_
                                    invalid 拒绝；WAITING_PERMISSION 中同 approval_id
                                    重投为幂等观察、不同 approval_id 请求为 typed
                                    approval_id_conflict 零状态变更不覆盖 pending；
                                    BLOCKED_APPROVAL 仍允许新合法请求；长 ID 第 129
                                    字符不同不得互相批准）；
                                 5) tool lifecycle 身份配对（TOOL_STARTED 必须建立
                                    非空 active_tool；TOOL_PROGRESS/TOOL_COMPLETED
                                    的工具身份必须与 active_tool 一致，缺失或不同均
                                    typed diagnostic 零状态变化；fs.read active 时
                                    fs.delete completed 不得关闭子相位；工具名不再
                                    [:128] 截断配对）
                                 适配：既有 28 项测试全数保留并适配更严格语义
                                 （WAITING 自环重投须带同 approval_id；tool.progress/
                                 completed 事件携带工具身份；max_payload_bytes 最小
                                 预算 128），新增 5 项 reviewer-locked 否证，专项 33

REVIEWER_PATCH_1               = 8 项 blocker 全部修复并逐一否证锁定：
                                 1) VERIFIED 在 16E 阶段 fail-closed（VB(verified)
                                    一律 unauthorized_verification；provenance/
                                    _private 不得冒充 authority；全状态全事件扫描
                                    VERIFIED 不可达）；
                                 2) normalizer/reducer 精确身份绑定（BackendEvent
                                    backend_id/run_id、Mapping 携带身份字段不一致
                                    一律拒绝；reducer 实际检查 backend_id 且构造
                                    要求非空 backend_id）；
                                 3) _seen 改为 event_id→canonical fingerprint
                                    （同 id 同内容 duplicate / 同 id 不同内容
                                    event_id_conflict / 非法事件不烧毁 id 可重放）；
                                 4) fallback event_id 纳入 sequence（同内容两次
                                    tool.started/completed 是两次事件；只有上游
                                    稳定 event_id 才声明强重投幂等）；
                                 5) payload 秘密值形态脱敏（message/stdout/error/
                                    list 内 Bearer/authorization/password/token/
                                    secret/api_key 形态）+ max_payload_bytes
                                    type-is-int 严格校验；
                                 6) approval.requested/resolved 绑定 approval_id
                                    （deny/timeout 后同 id approve 不得恢复
                                    RUNNING；不相关 id 不得改变状态）；
                                 7) TOOL_STARTED/TOOL_COMPLETED 不可丢、不可合并
                                    （critical）；只有 TOOL_PROGRESS/token delta
                                    可 drop/coalesce；
                                 8) 新增 7 项 reviewer-locked 否证测试
                                    （test_patch1a–1g）、删除重复 _drive 定义、
                                    GUI flake 措辞改为"未稳定复现，不声明已证伪"

EVENT_ENVELOPE_MODULE          = furina/agent/events/models.py（NormalizedEvent ——
                                 backend-neutral 不可变信封，字段至少含 event_id /
                                 backend_id / contract_id / run_id / sequence /
                                 occurred_at / received_at / kind / sanitized payload /
                                 lossy_payload / terminal / critical / provenance；
                                 **terminal/critical
                                 为派生字段**（由 kind 决定，来源方不得自报，防止
                                 "完成/成功"自证）；**lossy_payload 为派生判据
                                 （Reviewer Patch 4 + 5）**：payload 清洗是否丢失/改写
                                 了任何原始信息（秘密键脱敏、秘密值形态、字符串
                                 第 256 字符后截断、整体超预算截断、深度/非法值
                                 丢弃、控制字符替换、bytes 解码类型擦除、
                                 **tuple→list 类型擦除（Patch 5）**）——只携带
                                 布尔判据，**绝不保存/导出 raw secret 或其普通未
                                 加密摘要**；payload 构造时自动脱敏（秘密键
                                 精确词表 + **秘密值形态脱敏**（message/stdout/error/
                                 list 内 Bearer/authorization/password/token/secret/
                                 api_key 键值/头/凭证形态 → [REDACTED]；**Reviewer
                                 Patch 5：值支持 1 字符及以上/Unicode/常见特殊字符，
                                 quoted 值覆盖到配对引号（password="a b"），unquoted
                                 值至少覆盖到空白/行结束/明确结构分隔符——绝不只
                                 替换前缀残留后缀（password=abc@def 无 @def 残留），
                                 token_count/author/普通消息零误杀**）+ 控制字符
                                 清除 + 字符串限长 256 + 深度 8 + 总序列化
                                 **UTF-8 字节** <=4096B（len(encoded.encode("utf-8"))，
                                 多字节字符不得以字符数绕过预算）超限 _truncated
                                 （original_bytes 记录真实 UTF-8 bytes；truncation
                                 marker 自身也落在预算内）；**max_payload_bytes 严格
                                 校验**：type-is-int、非 bool、**最小预算 128B** <= n
                                 <= 1MiB，bool/float/低于最小预算/超上限构造即拒绝
                                 （不允许"声称允许 1 byte 却返回超预算 JSON"）+
                                 递归冻结 + 防御复制导出
                                 to_dict；**API-immutable（Reviewer Patch 3）**：
                                 构造完成后普通赋值/删除任何内部字段（_kind/
                                 _backend_id/_payload/_terminal/_sequence/… 全部
                                 slots 与公共属性）一律 AttributeError、原值不变
                                 （构造/to_dict/payload freeze/terminal+critical
                                 派生语义不变；**不把 Python immutability 宣称为
                                 进程安全边界**，仅保证正常 API 无法修改）；
                                 **payload 类型精确（Reviewer Patch 3）**：必须
                                 Mapping 或 None（None = 合法空 payload），list/str/
                                 int/任意对象等非 Mapping 显式载荷一律
                                 EventNormalizationError，不静默替换为 {}
                                 （sanitize_payload 双入口同样 fail-closed）；
                                 EventKind 17 类 canonical 枚举 +
                                 UNKNOWN_EVENT；EventPriority 三态 + classify_priority +
                                 EventBackpressurePolicy（纯策略，无队列））
STATE_REDUCER_MODULE           = furina/agent/events/reducer.py（WorkExecutionReducer
                                 —— 每 run 一个，构造绑定 backend_id+run_id+
                                 contract_id 身份，**事件任一身份不匹配 raise**
                                 （含 backend_id——此前只查 run/contract）；
                                 WorkExecutionView 不可变快照 + ReduceResult(applied/
                                 diagnostic/kind)；LEGAL_TRANSITIONS 只读导出）+
                                 normalizer.py（BackendEventNormalizer —— 16B
                                 BackendEvent / Mapping 形状 → canonical 信封；
                                 **身份不一致直接拒绝**：BackendEvent 的 backend_id/
                                 run_id、Mapping 携带的身份字段（backend_id/
                                 contract_id/run_id 及别名键）必须与构造绑定一致，
                                 非 str 或值不一致一律 EventNormalizationError，
                                 不静默改绑；词表对齐 Hermes _set_run_status 真实
                                 词表 queued/running/waiting_for_approval/stopping/
                                 completed/cancelled/failed + SSE 事件面 approval
                                 .request/tool.*/message.delta/reasoning*；**SSE
                                 done 哨兵按非权威帧标记 → UNKNOWN_EVENT**（绝不
                                 自造 completed）；**别名无歧义**（身份字段所有已出现
                                 别名逐一校验等于绑定值；event_id/sequence/时间戳/
                                 kind/payload 多别名同时出现等值允许、冲突值拒绝；
                                 显式出现但类型/范围非法不得当作缺失补值——有否证
                                 测试）；缺 event_id 时**按到达顺序派生（fallback id
                                 只纳入 backend/run 身份、canonical kind、sequence
                                 与独立递增的 arrival ordinal——**绝不包含/散列/派生
                                 自 raw payload**（Reviewer Patch 4：低熵秘密不得
                                 成为可枚举指纹）；每次
                                 到达唯一：显式 sequence 后接缺 sequence、重复显式
                                 sequence、混合流均不得碰撞；同内容两次事件 = 两次
                                 不同事件，不得被误去重）**、缺 sequence 按到达
                                 补序——同一输入流（fresh normalizer）重复归一结果
                                 完全一致；**Typed BackendEvent payload exactness
                                 （Reviewer Patch 3）：payload None = 合法空 payload、
                                 Mapping = 正常归一、list/str/int/任意对象等非
                                 Mapping 显式载荷一律 EventNormalizationError（不
                                 静默替换为 {}）**）
LEGAL_TRANSITIONS_LOCKED       = true（全部 14 个 WorkExecutionState 的合法转移表
                                 逐行锁定：IDLE/STARTING/RUNNING/WAITING_PERMISSION/
                                 BLOCKED_APPROVAL/CANCELLING/BACKEND_DONE_UNVERIFIED/
                                 VERIFYING/REPAIRING/终态；outcome 依赖的
                                 APPROVAL_RESOLVED（approve/deny/timeout，**必须
                                 绑定 approval_id**）与 VERIFICATION_BOUNDARY
                                 （start/failed/repair；verified 见下）单独分支；
                                 **approval.requested 绑定 approval_id 并进入挂起
                                 态，BLOCKED_APPROVAL 收到新请求 → 重新挂起
                                 （WAITING_PERMISSION）**；自环语义显式：
                                 RUNNING--run.started、WAITING--approval.requested、
                                 CANCELLING--stopping/stop、BDU--completed 确认）
COMPLETED_MAPS_UNVERIFIED      = true（backend completed **只**折算为
                                 BACKEND_DONE_UNVERIFIED；**VERIFIED 在 16E 阶段
                                 不可由公开事件抵达**：公开 reducer 对
                                 VERIFICATION_BOUNDARY(verified) 一律 fail-closed
                                 （unauthorized_verification typed diagnostic、
                                 零状态变更）——16E 无 verifier authority，provenance
                                 字符串/Python _private 属性均不得冒充 authority；
                                 16F 建立真实 verifier 后由注入权威通道开放。
                                 backend 词表含 "verified"/"verification.boundary"/
                                 done 哨兵一律归一 UNKNOWN_EVENT 非权威；有全状态
                                 全事件扫描否证：任何可达状态喂任何 EventKind，
                                 primary 永不成为 VERIFIED）
BACKEND_CAN_EMIT_VERIFIED      = false
DUPLICATE_IDEMPOTENT           = true 且精确化（**event_id→canonical fingerprint**
                                 去重：同 id 同内容（身份+kind+清洗后 payload）=
                                 duplicate_event；同 id 不同内容 =
                                 event_id_conflict（typed diagnostic、零变更）；
                                 **lossy payload 同 id 同 sanitized 内容 →
                                 event_id_ambiguous（Reviewer Patch 4 + 5：秘密脱敏/
                                 截断/深度或非法值丢弃/**tuple→list 类型擦除**不得
                                 静默当作幂等重投——同 event_id 不同 secret-bearing
                                 payload 或 list/tuple 形态互投不得返回
                                 duplicate_event，有否证测试）**；
                                 **被拒绝的事件不烧毁 id**——先非法后满足前置条件
                                 的同一事件可重放（有否证测试）；**只有上游显式
                                 提供的稳定 event_id 才声明强重投幂等**——fallback
                                 id 由非敏感字段（backend/run/kind/sequence/arrival）
                                 派生，仅在同一归一化流位置稳定，同内容两次事件是
                                 两次不同事件，不得被误去重）
OUT_OF_ORDER_FAIL_SAFE         = true（终态 CANCELLED/FAILED/VERIFIED/UNKNOWN 吸收：
                                 任何事件（除精确重复 id 与 UNKNOWN/PROTOCOL 纯观察）
                                 → terminal_absorbing:<state>:<kind> typed diagnostic
                                 且零状态变更；reconnect/progress 不得复活终态；
                                 乱序非终态事件按表裁决（非法 → illegal_transition）
                                 不静默改状态）
TOOL_RUNNING_SUBPHASE          = true 且精确化（TOOL_RUNNING 是子相位，不是
                                 primary：WorkExecutionView 分离 primary +
                                 tool_subphase + active_tool——tool.started 激活
                                 子相位（primary 保持 RUNNING）、tool.progress 为
                                 tick 不改变状态、tool.completed 退出子相位；primary
                                 变化自动清空子相位（completed 结束工具）；state
                                 属性在子相位激活时呈现 TOOL_RUNNING，其余呈现
                                 primary；**工具身份配对（Reviewer Patch 2 + 3）**：
                                 TOOL_STARTED 必须建立非空 active_tool（缺工具名/
                                 空名 → tool_identity_invalid 零变更）；TOOL_PROGRESS/
                                 TOOL_COMPLETED **显式携带**的工具身份必须与
                                 active_tool 一致（缺失 → tool_identity_invalid、不同
                                 → tool_identity_mismatch，均 typed diagnostic 零变更；
                                 **fs.read active 时 fs.delete completed 不得关闭
                                 子相位**；工具名不做 [:128] 截断配对，超长拒绝；
                                 **工具身份明确 lexical contract（Reviewer Patch 4）：
                                 tool/tool_name/name/toolId 所有别名 strip 后必须
                                 规范化一致，且以字母/数字开头、仅含
                                 [A-Za-z0-9._:-]、总长 <=128——内部空白（control-
                                 char 经 sanitizer 变为空格后同样词法非法）、斜杠、
                                 下划线开头及其它非法字符一律 tool_identity_invalid；
                                 TOOL_STARTED/显式 TOOL_PROGRESS/TOOL_COMPLETED
                                 共用同一规则；app.launch/browser.open/fs.read_file/
                                 fs.write_text/doc.create/comm.send_message 正样本
                                 通过，有否证测试**）；
                                 **TOOL_PROGRESS 无工具身份 = generic stream/progress
                                 tick（Reviewer Patch 3，取代 Patch 2 的"tick 也必须
                                 归因"）**：payload 未携带任何工具身份时在 RUNNING
                                 中合法 self-loop，不建立/不关闭/不改变 tool_subphase/
                                 active_tool——message.delta/reasoning/reasoning.delta
                                 无 tool 字段的真实 fixture 通过 reducer 且永远不能
                                 产生终态或 VERIFIED（有否证测试）；
                                 子相位非法序列（未开始即完成 / 已激活再开始）→
                                 typed diagnostic 零变更）
CRITICAL_EVENTS_DEFINED        = true 且精确化（16E 只做分类，durable queue/ledger
                                 属 16H：CRITICAL ⊇ terminal/approval/cancellation/
                                 disconnect/verification-boundary + run 生命周期 +
                                 protocol.error + **TOOL_STARTED/TOOL_COMPLETED
                                 （不可丢、不可合并的工具生命周期边界——丢/合并会
                                 破坏子相位成对语义）**；DROPPABLE = TOOL_PROGRESS
                                 （唯一可丢弃的 token delta）；COALESCIBLE 仅
                                 reconnect/unknown 观察；EventBackpressurePolicy
                                 .never_droppable/drop_allowed(under_pressure)/
                                 coalesce_allowed 有测试；token/progress 流不写成
                                 cognition truth——本包零 cognition 依赖）
PAYLOAD_BOUNDED_REDACTED       = true 且精确化（秘密**键**（password/api_key/
                                 authorization/access_token/client_secret/token/
                                 x-api-key/x-authorization 等精确词表 + 紧凑形）→
                                 [REDACTED]；**秘密值形态**（message/stdout/error/
                                 list 内 "Authorization: Bearer xyz" /
                                 "password=hunter2" / "api_key: sk-…" / JSON
                                 '{"access_token":"…"}' 等键值/头/凭证形态）→
                                 标签保留、秘密部分 [REDACTED]；**Reviewer Patch 5：
                                 值支持 1 字符及以上（password=x/ab/token=短）、
                                 Unicode（password=秘密）、常见特殊字符（p@ss/
                                 abc@def），quoted 值覆盖到配对引号（password=
                                 "a b"），unquoted 值至少覆盖到空白/行结束/明确
                                 结构分隔符——绝不只替换前缀残留后缀（password=
                                 abc@def 无 @def 残留，有否证测试），任一真实替换
                                 lossy=true**；token_count/author
                                 等含子串合法键与自然语言不误伤（负向对照
                                 token_count=5/author=alice/ordinary message 零
                                 误杀，有否证测试）；控制字符清除；
                                 字符串限长 256；超预算载荷 → 确定性 _truncated
                                 标记；非 JSON-safe 对象整键丢弃；payload 递归
                                 冻结不可变；max_payload_bytes type-is-int 严格
                                 校验（bool/float/低于最小预算 128B/0/负/超 1MiB
                                 构造即拒绝；**超限判据是真实 UTF-8 字节
                                 len(encoded.encode("utf-8"))**——字符数 <= 预算但
                                 字节数超预算的载荷必须截断，original_bytes 记录
                                 真实 UTF-8 bytes；truncation marker 自身也不超
                                 预算——有否证测试）；**lossy 判据（Reviewer
                                 Patch 4 + 5）**：清洗是否丢失/改写原始信息（秘密键
                                 脱敏、秘密值形态、第 256 字符后截断、整体超预算
                                 截断、深度/非法值丢弃、控制字符替换、bytes 解码
                                 类型擦除、**tuple→list 类型擦除（Patch 5）**）由
                                 信封 lossy_payload 明确携带——**只保存
                                 布尔判据，绝不保存/导出 raw secret 或其普通未加密
                                 摘要**；去重/幂等层对 lossy 内容保守 ambiguous
                                 （有否证测试））
APPROVAL_ID_BOUND              = true 且精确化（Reviewer Patch 2 + 3：**approval_id
                                 明确 lexical contract（Patch 3）**——以字母/数字
                                 开头、仅含 [A-Za-z0-9._:-]、总长 <=128；**内部空白/
                                 control-char 经 sanitizer 变成空格后同样词法非法
                                 拒绝**（"ap\x00bad" 清洗为 "ap bad" →
                                 approval_id_invalid）、不接受内部空白/截断/别名冲突；
                                 approval.requested/resolved **必须精确绑定
                                 approval_id**——**禁止 [:128] 静默截断**，显式
                                 非法/超长（>128）/control-char/多别名冲突 ID 直接
                                 approval_id_invalid typed diagnostic 零变更（长 ID
                                 第 129 字符不同不得互相批准，有否证测试）；payload
                                 显式或回退请求事件自身 canonical event_id——确定性
                                 绑定、不虚构）；resolved 只能作用于当前挂起的
                                 approval_id，不相关/缺失 → approval_id_mismatch
                                 typed diagnostic 零变更；**WAITING_PERMISSION 中
                                 幂等观察 = 同 approval_id + 同请求内容（Patch 3：
                                 pending 除 approval_id 外保存 canonical sanitized
                                 request fingerprint；同 id 但 tool/scope/args/其它
                                 payload 不同 → approval_request_conflict 零变更，
                                 绝不覆盖 pending，以原请求仍可 approve；**Patch 4：
                                 lossy 内容（秘密脱敏/第 256 字符后截断/整体截断/
                                 深度或非法值丢弃）同 id 同 sanitized 内容 →
                                 approval_request_ambiguous 零变更、绝不覆盖
                                 pending——同 approval_id 的 password AAA→BBB、仅
                                 第 257 字符不同都不得判定幂等，有否证测试）**；不同
                                 approval_id 请求为 approval_id_conflict（零变更，
                                 **绝不覆盖 pending**）；**resolution 后同时清除
                                 pending id 与 fingerprint（Patch 3）**；
                                 **BLOCKED_APPROVAL 仍允许新合法 approval 请求
                                 （新 id → 重新挂起）**；approve/deny/timeout 消费
                                 即销毁（一次性）；deny/timeout 后同 approval_id 的
                                 approve 不得恢复 RUNNING；恢复必须经新的
                                 approval.requested（新 approval_id）；**outcome 别名
                                 一致性（Patch 3：outcome/decision/resolution/result
                                 所有已出现别名规范化一致，approve≈approved≈allow≈
                                 granted 等价；approve 与 deny/timeout 冲突 →
                                 outcome_conflict typed rejection 零状态变化、pending
                                 保留；非 str/空/未知值 fail-closed；verification
                                 outcome 别名同样一致性检查（start vs failed 冲突
                                 拒绝），避免相邻 first-key-wins）**；畸形 outcome
                                 拒绝但不消费挂起请求——有否证测试）
WORK_STATE_WRITTEN_TO_C7       = false（工作域状态绝不写 C7；仅 16G 六态终态折算）
C6_EVENTS_APPENDED             = false（backend 运行事件非 C6 真值；16E 只定义
                                 投影接口语义，C6 append 归 16G；不引入重复 C6 词表）
HERMES_SHAPED_INPUT_ONLY       = true（Hermes-shaped fixture 只作为输入映射测试；
                                 NormalizedEvent/WorkExecutionState 生产类型零
                                 Hermes 专属字段——无 _run_statuses/
                                 _stopping_run_ids/chatToolEventFromRunEvent 等，
                                 有断言锁定）
DETERMINISTIC_REPLAY           = true 且精确化（同一事件流在全新 reducer 上重复
                                 重放结果完全一致——fallback id 确定性（arrival
                                 ordinal 独立递增：fresh normalizer 重放同一完整
                                 输入流 → 同一 id 序列；显式 sequence 后接缺
                                 sequence、重复显式 sequence、混合流均不碰撞——
                                 有否证测试）+ fingerprint 去重 + 纯转移表 + 注入
                                 时钟；同 reducer 重投整流（上游稳定 id）→ 全部
                                 duplicate 且状态与计数不变；processed_count/
                                 max_sequence 确定性观测；**lossy 判据不破坏确定性
                                 （Reviewer Patch 4）**：lossy_payload 由清洗树
                                 确定性推导（无实例随机 key——选择保守方案 A 而非
                                 keyed discriminator），fresh normalizer/reducer
                                 重放同一完整事件流产生相同状态转移结果，有否证
                                 测试）

C1_C7_SCHEMA_CHANGED           = false
PRODUCTION_FILES_CHANGED       = 仅 furina/agent/events/ 包内自有模块
                                 （models.py / reducer.py）——
                                 Reviewer Patch 5 只修改 models.py（嵌入秘密值正则
                                 重写 + tuple 类型擦除 lossy）+ reducer.py（422
                                 行尾空格）+ 16E 测试
                                 + closeout；normalizer.py 未改；未修改任何其它生产
                                 文件（16A
                                 work_contract.py / 16B backend/ / 16D approval/ /
                                 agent_runtime.py / permission.py / app.py 等零改动；
                                 16A/16B/16D frozen contracts 未触碰）
TEST_FILES_CHANGED             = 仅新增 tests/agent/integration/test_phase16e_event_normalization.py
                                 （53 个测试函数 = 任务书 §7 十二项 + 额外锁定 4 项
                                 + Reviewer Patch 1 否证 7 项 + Reviewer Patch 2
                                 否证 5 项 + Reviewer Patch 3 否证 9 项 + Reviewer
                                 Patch 4 否证 6 项 + Reviewer Patch 5 否证 5 项；
                                 既有 48 项全数保留零改动，
                                 Patch 3 对 test_patch2e 一条断言的语义适配保留）
TARGETED_TESTS                 = tests/agent/integration/test_phase16e_event_normalization.py：
                                 53 passed（Reviewer Patch 5 否证 5 项 test_patch5a–5e
                                 覆盖 3 组 micro-blocker；Reviewer Patch 4 否证 6 项
                                 test_patch4a–4f
                                 覆盖 3 组 blocker；Reviewer Patch 3 否证 9 项
                                 test_patch3a–3i
                                 覆盖 4 组 blocker；既有 42 项除 Patch 3 那一条必然
                                 语义适配外零改动全过）。任务书
                                 §7 十二项逐项锁定：
                                 1) 完整合法转移表（LEGAL_TRANSITIONS 逐行 + approval
                                    outcome 分支（approval_id 绑定）+ verification
                                    .boundary 分支 + TOOL_RUNNING 子相位转移）；
                                 2) 非法转移 fail-safe（17 组 (state,kind) 反例 +
                                    子相位非法序列：illegal_transition: typed
                                    diagnostic + 快照/计数/sequence 全零变更）；
                                 3) completed → BACKEND_DONE_UNVERIFIED 且全路径
                                    永不 VERIFIED（backend 词表 token 含 verified/
                                    verification.boundary/done 全部归一 UNKNOWN 且
                                    零转移；VB(verified) fail-closed 拒绝）；
                                 4) duplicate/conflict/乱序（event_id→fingerprint：
                                    同 id 同内容 duplicate、同 id 不同内容
                                    event_id_conflict、非法事件不烧毁 id 可重放；
                                    乱序不得回退终态）；
                                 5) 未知外部事件 typed UNKNOWN_EVENT 可观察
                                    （processed_count 计数）但非权威（零转移，
                                    任意状态含终态均为纯观察）；
                                 6) approval 全路径（requested→resolved approve /
                                    deny→blocked→新请求→approve）与 cancellation
                                    全路径（stop→CANCELLING→cancelled/failed）；
                                 7) disconnect→UNKNOWN 策略边界（五状态出发 +
                                    UNKNOWN 吸收 + reconnect 不复活终态）；
                                 8) critical 事件分类（17 类逐一断言 + 工具生命周期
                                    边界 critical + 信封派生字段 + 背压策略纯声明）；
                                 9) payload 脱敏与大小上限（秘密键 + 秘密值形态 +
                                    误伤豁免 + 控制字符 + 限长 256 + 超预算
                                    _truncated + 递归冻结不可变 + 非 JSON-safe
                                    丢弃 + max_payload_bytes 严格校验）；
                                 10) WorkExecutionState 零写入 C7/C6（子进程导入
                                     守卫：events 包不拉入 furina.cognition；真实
                                     CognitionHub store 跑完完整会话后
                                     life_events/agent_tasks/agent_task_steps 零行）；
                                 11) Native 词表与 Hermes-shaped fixture 归一为
                                     相同语义（状态序列完全一致；SSE done 哨兵
                                     非权威不推进；生产类型无 Hermes 字段）；
                                 12) 同一事件流重复重放确定性（3 次 fresh replay
                                     结果逐项一致；同 reducer 重投幂等）。
                                 额外锁定：信封字段校验 fail-closed（11 组非法值）/
                                 reducer backend_id+run_id+contract_id 身份绑定
                                 （不匹配 raise + 未归一 dict 拒绝 + 构造要求非空
                                 backend_id）/ sequence+processed_count 观测 /
                                 信封 to_dict 防御复制（工具边界 critical 派生）。
                                 Reviewer Patch 1 否证（7 项，见 REVIEWER_PATCH_1
                                 逐条对应 test_patch1a–1g）
                                 Reviewer Patch 2 否证（5 项，见 REVIEWER_PATCH_2
                                 逐条对应 test_patch2a–2e；另含既有 28 项对
                                 更严格语义的适配说明）
                                 Reviewer Patch 3 否证（9 项，见 REVIEWER_PATCH_3
                                 逐条对应 test_patch3a–3i）
                                 Reviewer Patch 4 否证（6 项，见 REVIEWER_PATCH_4
                                 逐条对应 test_patch4a–4f）
                                 Reviewer Patch 5 否证（5 项，见 REVIEWER_PATCH_5
                                 逐条对应 test_patch5a–5e）
AGENT_EVENT_REGRESSION         = pytest tests/agent tests/test_agent_tools.py
                                 tests/test_skeleton.py：369 passed
                                 （15 warnings 为既有线程 ResourceWarning 类告警，
                                 与本阶段无关；16D 的 316 + 16E 专项 53 = 369）；
                                 另跑 16A/16B/16D 专项
                                 tests/agent/integration/test_phase16b_execution_backend.py
                                 test_phase16a_work_contract.py
                                 test_phase16d_permission_approval.py：198 passed
                                 （161 + 37；与 16E 专项合并跑 251 passed）
COGNITION_SUITE                = pytest tests/cognition：279 passed（Phase 15
                                 cognition/store 契约不变；events 包零 cognition
                                 依赖有专项断言）
FULL_SUITE                     = .venv/Scripts/python.exe -m pytest -q：1614 passed,
                                 0 failed（198.10s，exit 0），较 Patch 4 的 1609 恰
                                 +5（16E Patch 5 新增否证；Patch 4 的 1609 较
                                 Patch 3 的 1603 恰 +6）。
                                 GUI flake 说明：16E 初版曾出现一次
                                 tests/test_gui_integration.py::
                                 test_gui_timer_advances_runtime 失败（Qt 定时器在
                                 满载 full suite CPU 争用下未在 drive 窗口内推进
                                 生命周期）；该测试隔离运行通过、Patch 1/2 全量亦
                                 通过，**未稳定复现，不声明已证伪**——16E 零改动
                                 GUI/AnimationRuntime/EventBus 路径，但相关性判定
                                 留给外部验收

REMAINING_GAPS                 = 1) 按 brief 无 Hermes(16C)/verifier+repair(16F)/
                                   durable queue+ledger+recovery(16H)/C7 commit
                                   (16G)/MCP——全部留待对应子阶段；2) 事件面仍为
                                   进程内状态机，未接入 NativeAgentRuntimeBackend
                                   submit/events 生产 wiring 与全局 EventBus 枚举
                                   （16E 只定义 envelope+reducer 契约；消费接线属
                                   后续子阶段）；3) VERIFYING/REPAIRING 的转移规则
                                   已定义（16F 将消费 VERIFICATION_BOUNDARY kind
                                   并注入真实 verifier authority 开放 VERIFIED 通道），
                                   16E 不实现 verifier 本身且 verified fail-closed；
                                   4) 背压只做分类声明，有界队列/丢弃策略实现在
                                   16H；5) 基线已有 untracked（data/assets_v2/、
                                   scripts/assets_v2/、_night_*、nul）保持未触碰；
                                   6) 说明（Reviewer Patch 3 更新）：payload 内
                                   approval_id 的 control-char 在信封层被确定性
                                   清洗（\x00→空格，有测试断言），reducer 层以
                                   **明确 lexical contract** 拒绝清洗后的内部空格
                                   （"ap\x00bad"→"ap bad"→approval_id_invalid，
                                   有否证测试）——不再有"control-char 经清洗后
                                   被当作合法 id"的路径；
                                   7) 说明（Reviewer Patch 4 更新）：lossy 内容
                                   （含秘密字段的 payload）重投保守返回 typed
                                   ambiguous——即使是**完全相同**的含秘密 payload
                                   重投也不再判定幂等（无法在不保存 raw secret 或
                                   其普通未加密摘要的前提下确认 raw 相同；这是
                                   保守方案 A 的有意取舍，任务书明确允许；选择 A
                                   而非 keyed discriminator 以保持 fresh
                                   normalizer/reducer 重放确定性；如需强重投幂等，
                                   上游应提供稳定 event_id + 非 lossy payload）；
                                   8) 说明（Reviewer Patch 5 更新）：嵌入秘密值脱敏
                                     收紧到 **1 字符及以上**（任务书要求 password=x /
                                     token=短 / Bearer ab 等短值必须完整脱敏），
                                     unquoted 值至少覆盖到空白/行结束/结构分隔符——
                                     "Bearer of good news" 等自然语言中位于
                                     bearer/basic/digest 之后的 1+ 字符单词会被
                                     （与 password: 后接单词同理，属"密钥+值"形态
                                     的有意取舍，负向对照 token_count=5 / author=
                                     alice / ordinary message 不受影响）；
                                     9) 说明（Reviewer Patch 5 更新）：tuple→list
                                       类型擦除一律 lossy（方案 A）——同 event_id 的
                                       list/tuple 互投保守 event_id_ambiguous 而非
                                       duplicate（无法在不保存 raw 的前提下确认
                                       raw 相同；若业务需要强幂等，上游应保持 payload
                                       类型稳定）；
READY_FOR_REVIEW               = YES
```

No fabricated PASS or test totals. External reviewer owns `16E_PASS`.
