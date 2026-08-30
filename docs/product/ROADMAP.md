# Furina Desktop AI — Canonical Roadmap

> STATUS = CURRENT canonical product roadmap.
> Historical plans remain under `docs/archive/legacy-plan/`; later Phase task briefs may refine
> implementation detail but must not silently renumber this roadmap.
> Status vocabulary: **implemented / in_progress / pending**. Review outcomes belong in each
> Phase closeout and are not duplicated here.
> POST-16 PLAN = **FROZEN**. Its execution authority is
> [`docs/phase/00_PHASE_17_24_PLANNING_AUTHORITY.md`](../phase/00_PHASE_17_24_PLANNING_AUTHORITY.md).
> Renumbering, moving ownership between Phase 17–24, or changing the Phase 23/24 release boundary
> requires an explicit roadmap decision and reviewed documentation patch.

## Phase 13 — Core Runtime Closure（implemented）

Core Runtime V1、Windows exact-SHA evidence、Agent Runtime evidence 与 backend RC1 基线已经
冻结。遗留人工体验项不改变后续 Phase 编号。

## Phase 14 — Cognitive Foundation & Universal Agent Expansion（implemented）

- C1–C7、CognitionHub、ContextAssembler、Consolidator 与 Canon retrieval；
- Universal Agent Core、Capability Registry、Planner V2；
- Filesystem、Documents、Application Catalog、Browser/Desktop foundation；
- Communication/Calendar provider interfaces；
- C7 Agent Task History 与 runtime cognition boundary。

本阶段只保留了 Work Willingness、Character Body 与 Integrated Manual 的接口/命名预留；
它们分别归属 Phase 17、Phase 20 与 Phase 24，不得回填到 Phase 14。

## Phase 15 — Cognitive Life（implemented）

完成七个权威认知 Store 的真实性、时间性、检索、关系防刷、来源链与集成终门。
以下行为永久延后至 Phase 17：

- P17-D1：plan/goal proactive follow-up；
- P17-D2：relationship climate → behavior policy。

## Phase 16 — Work Sovereignty & Verified Agent Execution（in_progress）

目标是让 Furina 在明确授权下可靠、可审批、可验证、可取消、可恢复地完成工作：

- immutable WorkContract；
- ExecutionBackend protocol、registry 与 Hermes adapter；
- permission/approval boundary；
- backend event normalization；
- independent verification 与 bounded repair；
- durable recovery、idempotency、cancellation 与 backpressure；
- verified C7/C6 exactly-once truth commit；
- integrated work-sovereignty final gate。

Canonical implementation order：

```text
16A → 16B → 16D → 16E → 16C → 16F → 16H → 16G → 16I
```

Phase 16 只拥有技术可行性、权限与执行真值；角色主观愿不愿意做属于 Phase 17。

## Post-16 Character & Life Manual Gate（pending，非编号 Phase）

在进入 Character Agency 前进行一次真实 Windows/真实服务人工体验验收：人格、长期对话、
记忆、关系、主动行为、工作表达和桌面生命循环。它是体验 Gate，不占用新的 Phase 编号。

## Phase 17 — Character Agency & Work Willingness（pending）

执行入口：[`docs/phase/Phase_17/_INDEX_README.md`](../phase/Phase_17/_INDEX_README.md)

- willingness / refusal / negotiation；
- Persona、关系与情绪驱动的表达和主观工作偏好；
- P17-D1 计划/目标主动跟进；
- P17-D2 关系气候到接近、沉默、主动行为的策略；
- 主动关心、提醒和可解释的打断；
- Persona pressure/regression suite。

Phase 17 不得扩张 WorkContract、绕过审批或把技术不可行解释成角色意愿。

## Phase 18 — Computer Control & Office Automation（pending）

执行入口：[`docs/phase/Phase_18/_INDEX_README.md`](../phase/Phase_18/_INDEX_README.md)

- 浏览器 DOM、Accessibility 与必要的视觉辅助控制；
- 标签页、下载、上传、表单和文件跨应用搬运；
- Word、Excel、PowerPoint、PDF；
- VS Code、终端与 Coding Agent delegation；
- 邮件读取、分类、摘要、草拟和确认后发送；
- 日历、会议、提醒和任务管理；
- 可验证、可取消的跨应用办公工作流。

验收面向完整任务链，而不是孤立的“能点击控件”。所有真实副作用继续经过 Phase 16。

## Phase 19 — Connected Services & Communications（pending）

执行入口：[`docs/phase/Phase_19/_INDEX_README.md`](../phase/Phase_19/_INDEX_README.md)

- 钉钉、飞书、企业微信等正式接口；
- 微信、QQ 等桌面客户端的受控自动化；
- 统一 Channel Adapter、联系人身份解析与跨平台收件箱；
- 消息摘要、建议回复、代拟回复及发送前风险确认；
- 日程、生日、节日、主动关怀与通知降噪；
- 音乐、媒体与内容平台的合规控制；
- 面向工作与生活服务的产品控制台/UI。

平台能力不得绕过平台规则、联系人确认、Phase 16 权限或 Single Mouth。

## Phase 20 — Desktop Embodiment & Visible Action（pending）

执行入口：[`docs/phase/Phase_20/_INDEX_README.md`](../phase/Phase_20/_INDEX_README.md)

- 透明桌面窗口与 sprite/APNG/WebP runtime；
- 多方向、移动、路径、surface、碰撞和关键 UI 避让；
- 点击、摸头、拖拽、喂食及生活动作；
- RuntimeFrame → 唯一身体表现；
- 思考、执行、等待审批、验证、修复和终态的可见反馈；
- 暂停、隐藏和紧急停止。

身体只能表现真实工作状态，不能反向伪造任务成功。

## Phase 21 — Production Art & Animation Library（pending）

执行入口：[`docs/phase/Phase_21/_INDEX_README.md`](../phase/Phase_21/_INDEX_README.md)

- Identity Lock、方向一致性与角色拓扑一致性；
- neutral/walk/sit/sleep/eat/play/pet/poke/work 等标准动作；
- 表情、动作、道具、图层、遮挡、多方向与过渡帧；
- Alpha/边缘/碎屑/运行尺寸 QC；
- manifest、anchor、baseline、provenance 与自动验收；
- 素材缺失时的安全 fallback。

当前 Night Asset 流属于 Phase 21 的前置 Art Alpha，不进入 Phase 16 代码主线。

## Phase 22 — Voice Interaction（pending）

执行入口：[`docs/phase/Phase_22/_INDEX_README.md`](../phase/Phase_22/_INDEX_README.md)

- ASR、push-to-talk、可选 wake word 与 TTS；
- 合法、可持续使用的角色音色方案；
- 流式语音、barge-in、打断与话轮仲裁；
- 情绪、语速、停顿、语气和 Lip/Speech Sync；
- 语音与文字 Single Mouth；
- 噪声、误唤醒、隐私指示和麦克风总开关。

## Phase 23 — Eyes & Multimodal Perception（pending）

执行入口：[`docs/phase/Phase_23/_INDEX_README.md`](../phase/Phase_23/_INDEX_README.md)

- 屏幕捕获、Accessibility Tree、OCR 与 UI 元素检测；
- 浏览器、图片、图表和文档版面理解；
- 窗口/控件空间定位和指代理解；
- 敏感区域、密码框、支付与隐私窗口屏蔽；
- 本地优先、可见观察指示和工作过程回放；
- Eyes → Planner → Phase 16 permission → execution → independent verification。

视觉观察不是成功证据，不能仅凭截图声明任务完成。

## Phase 24 — Integrated Product, Character Platform & Release（pending）

执行入口：[`docs/phase/Phase_24/_INDEX_README.md`](../phase/Phase_24/_INDEX_README.md)

### Integrated product and manual

- 人格、记忆、关系、Agency、工作、权限与恢复的全链路人工验收；
- Browser/Office/Email、Connected Services、Body、Art、Voice 与 Eyes 集成；
- 长时间运行、Windows 启动/更新/卸载、数据备份与最终 Integrated Life Manual。

### Character interface

在不重写 Furina 的前提下抽象 `CharacterProfile`、`CanonProvider`、`PersonaPolicy`、
`DialogueStyle`、`EmbodimentProfile`、`VoiceProfile`、`AssetPack`、
`RelationshipPolicy` 与 `AgencyPolicy`。Furina 仍是默认且最完整的第一实现。

### Optional multi-character foundation

每个角色的人格、记忆、关系、声音、身体、意图和状态必须隔离；可以共享通用执行能力，
但不能共享人格真值，也不能用单一 prompt 假装成两个独立角色。Phase 24 只要求接口和
协调架构成立，不强制立即制作第二个角色。

### Release

安装包、自动更新、首次启动引导、权限控制台、紧急停止、数据导出/删除、Provider/插件
管理、性能与电量优化、崩溃诊断、Stable/Beta 通道和最终用户手册。

## Canonical mainline

```text
Phase 13–15  Runtime / Cognition / Cognitive Life foundations
        ↓
Phase 16     Governed, verified and recoverable work execution
        ↓
Manual Gate  Character and life experience acceptance
        ↓
Phase 17     Character Agency & Work Willingness
        ↓
Phase 18     Computer Control & Office Automation
        ↓
Phase 19     Connected Services & Communications
        ↓
Phase 20     Desktop Embodiment & Visible Action
        ↓
Phase 21     Production Art & Animation Library
        ↓
Phase 22     Voice Interaction
        ↓
Phase 23     Eyes & Multimodal Perception
        ↓
Phase 24     Integrated Product, Character Platform & Release
```
