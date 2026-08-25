# Phase 10.5 — Backend Freeze Full Audit（Release Candidate Audit）

> 目标：**证明我们现在冻结的东西真的值得被冻结**，而不是重新讨论"Personality 要不要再加参数"。
> 以审查为主；结论分四类：`BLOCKER` / `SHOULD_FIX_BEFORE_FRONTEND` / `ACCEPTED_TECH_DEBT` / `FRONTEND/FUTURE`。
> 只对 BLOCKER 解冻并做**最小**修复；其余**默认不修改生产代码**。

---

## 0. 审计方法

- 通读冻结的 15 个模块的真实代码（不是看测试/报告）。
- 对每个风险点做**最小可复现实验**（线程/DB/事件）。
- 检查 265 个测试在**证明什么**、是否掩盖了真实运行时路径（单线程/空 DB 掩蔽）。
- 全程零修改生产代码（直到确认 BLOCKER 并获准最小修复）。

## 1. 总体判断

```text
80% FREEZE 成立
15% 小型 cleanup（SHOULD_FIX，可在 closeout 修）
5% 真正 BLOCKER（1 项，必须解冻最小修复）
```

**未发现需要推翻整个后端的证据。** 各层因果实验是扎实的。但发现 **1 项真 BLOCKER**、**3 项 SHOULD_FIX**、以及若干 accepted debt。下表为审计矩阵。

## 2. Audit Matrix

| System | Architecture | Causality | Ownership | Long-run | Failure | Status |
|---|---|---|---|---|---|---|
| Needs | ✅ | ✅ | ✅ StateEngine | ✅ | ✅ | FREEZE |
| Emotion | ✅ | ✅ | ✅ EmotionEngine | ✅ | ✅ | FREEZE |
| Personality | ✅ | ✅ | ✅ Motivation/Personality | ✅ | ✅ | FREEZE |
| Relationship | ✅ | ✅ | ⚠️ 双写入路径 | ✅ | ✅ | SHOULD_FIX |
| Identity | ✅ | ✅ | ✅ | ✅ | ✅ | FREEZE |
| World | ✅ | ✅ | ✅ WorldPerception | ✅ | ✅ | FREEZE |
| Memory | ✅ | ✅ | ⚠️ 线程+所有权 | ⚠️ 线程 | ⚠️ 线程 | **BLOCKER** |
| Dialogue | ✅ | ✅ | ✅ | ✅ | ✅ | FREEZE |
| Embodiment | ✅ | ✅ | ✅ | ✅ | ✅ | FREEZE |
| Frame | ✅ | ✅ | ✅ | ✅ | ✅ | FREEZE |

---

## 3. BLOCKER（唯一解冻项）

### B1. MemoryStore 跨线程访问（LifeBrain 在后台线程碰 SQLite）→ 真 BLOCKER

**问题**：`MemoryStore.__init__` 用 `sqlite3.connect(str(db_path))`（默认 `check_same_thread=True`），
在主线程打开连接。但 `Scheduler._drive_life` 把 LifeBrain 决策放到**后台线程**
（`threading.Thread(target=_decide).start()`，scheduler.py L470-507），而 `LifeBrain.decide()` → `build_snapshot()`
（life_brain.py L304）→ `self.memory.retrieve()`（L213）→ `MemoryStore.query()`/`insert()`。

**证据（最小复现）**：
```
background thread sqlite result: ProgrammingError('SQLite objects created in a thread can only be used in that same thread...')
```
- 该错误在 `_decide` 的 `except Exception`（scheduler.py L502）里被**吞掉** → `_pending_life_decision = None`。
- 于是每次 LifeBrain 决策实际上**静默回退到本地 utility**（`_local_decision`/`generate_intent`），
  LLM 高层生命决策在运行时**从未真正生效**（一旦 memory ≥1 行）。

**为何测试没抓到**：
- 所有 `test_three_brain` 都在**主线程**调用 `LifeBrain(fake)`，且不构造真实 `MemoryStore`；
- workspace 的 `furina.db` 当前为**空**（memory=0 rows），`retrieve()` 在无数据时也许不报错或未走该路径。
- 这是"空 DB + 单线程测试"对真实多线程路径的**系统性掩蔽**。

**影响**：不崩溃（被吞了），但**架构意图被破坏**——三脑的 LifeBrain 本该做真正决策，实际被降级为本地规则；
而且这是**每次决策都发生**，不是偶发。

**修复方向（最小）**：
1. `MemoryStore.__init__` 用 `sqlite3.connect(str(db_path), check_same_thread=False)`。
2. 给 `MemoryStore` 加一个 `threading.Lock`（对 `insert/query/delete/commit`），
   因为即使 `check_same_thread=False`，**并发写**仍会报错（已复现 `OperationalError`/`InterfaceError`）。
   （或用"写入队列/单写线程"替代；但 Lock 是最小改动。）
3. 保持 `retrieve()` 里"读中带写增强（reinforce）"——但必须持锁。

**结论**：**BLOCKER，允许解冻，最小修复。**（修复后需新增一条"后台线程调用 retrieve 不抛异常"的测试。）

---

## 4. SHOULD_FIX_BEFORE_FRONTEND（pending closeout）

### S1. Relationship 双写入路径（真重复真相来源）
- 正式路径：`RelationshipEngine.apply(ev)`（带 decay、trust-slow、事件语义增量）。
- 旁路（并行真相）：
  - `app._on_meaningful_interaction`（app.py L243）`memory.apply_relationship({...})` 直接 bump，
    **绕过** `RelationshipEngine.apply()`（没有 trust-slow / 没有事件表 / 没有与 decay 耦合）。
  - `scheduler._on_interaction`（L285/L722）也可能走 `relationship.apply(ev)` 或 fallback 直接改 `me.relationship`。
- 二者触碰**同一个** RelationshipState 对象（app.py L54 `RelationshipEngine(self.memory.relationship)`），
  所以不造成**数据**损坏，但会造成**语义**漂移（同一关系，两种涨落规则）。
- **建议**：统一到 `RelationshipEngine.apply()` 单一入口；移除 `MemoryEngine.apply_relationship` 旁路
  或让后者委托给前者。**属于 SHOULD_FIX，可在 closeout 修，非 BLOCKER。**

### S2. 行为反重复存在 3-4 层重叠"补丁"（patch 层）
同时存在：
1. `BehaviorMotivation._category_penalty` + `_activity_penalty`（score 期降权，L462-484）
2. `BehaviorMotivation._observation_crush_guard`（observe>50% 压，L486）
3. `LifeBrain._apply_variety`（decision 期切换，repeat>=2，L478）
4. `Scheduler._anti_collapse`（category>=3 强制换，scheduler L665）
- 四个机制**都在修同一个问题**（别卡在同一行为/类别）。每个都曾为修某个具体测试/回归而加，
  现在叠加，使行为难以推理、阈值互相耦合。
- **建议**：保留 **1 个主反塌缩入口**（推荐 `LifeBrain._apply_variety` 在决策期全局做，或 `BehaviorMotivation` 在评分期做），
  其余收敛/降权。**保留但标为 debt；不做大改，避免破坏 265 测试。** 属 SHOULD_FIX / TOP 层清理。

### S3. Identity 双重 appraise（重复计算，非 bug）
- `BehaviorMotivation._appraise`（L429）与 `LifeBrain.build_snapshot`（L238）都调用 `character_identity.appraise(...)`。
- 只读、确定性，无状态——**不造成错误**，但同一情境被解释两次（一次喂 Motivation 候选，一次喂 Brain prompt）。
- 属轻微冗余。**可接受，未来收敛到一个 CharacterAppraisal 缓存。**

### S4. `body_snapshot()` 仍保留为只读别名
- Phase 10 已把它收敛为读取 `_last_frame.body` 的别名，不再是独立契约；但**方法仍在公开**。
- 前端若误用会重新形成第二条读路径。**SHOULD_FIX：标记 deprecated 或删除，只留 `current_frame()`。**

---

## 5. ACCEPTED_TECH_DEBT（不修，写进 freeze 声明）

- **LLM 实跑 god-reference 抽样（30 ordinary / 30 triggered）未做**：由确定性 gate 单测证明"不错误禁止"，
  真实 glm 用不用由模型定。非阻塞，符合 §25。
- **72h smoke 未作为独立独占跑**：24h surrogate（3000 tick）已覆盖全链；72h 只需延长 N。
- **glm-4v-flash 对话略平**：属模型/前端表现，不是后端结构。
- **memory relevance 可更精细**：现有 context= 精确匹配 + importance + recency，够用。
- **`_to_memory` 用 `row.keys()` 判断迁移列**：稳健，但每次读都要 keys()，略慢；可接受。
- **frame 发布间隔 1.0s**（非"每 semantic change 精确触发"）：语义变化低频，足够。

---

## 6. FRONTEND / FUTURE（不在本审计范围，属 Phase 11-15）

- Animation Runtime（帧/插值/timing）、Asset Resolver 增强、Desktop Spatial Runtime、Walk/Path、
  Speech bubble UX、TTS、Window UX、Product UX、Agent capability expansion。
- Frame 尚未被前端真正消费 body（仍经 Adapter 投影素材），Phase 11 切换。

---

## 7. 审计通过但需记录的点

- **EventBus 无反馈环**：`CHARACTER_FRAME_UPDATED` 目前仅发布、无订阅者，无环；
  现有 interaction→emotion/relationship→LifeBrain→决定 是**单向**（无 A→B→C→A 递归）。
- **Scheduler 时间语义**：三档 tick（fast/medium/slow）由 Clock 驱动，`Ticker.tick` 用 wall-clock `now` 求 dt；
  medium 只在此处更新 Needs/Emotion/Relationship/World，**无"一秒更新两遍"**；`update_needs` 只在 `_tick_medium` 调用一次。
  → **没有 dt 重复应用问题**（此前 surrogate 的 dt 失真已在本轮实际运行时被修正，runtime 用真实 dt）。
- **LLM 边界**：LifeBrain 只喂候选空间并选 activity（不生成台词）；DialogueBrain 只生成 speech（不决定意图）；Agent 只执行。无职责重叠漂移。
- **Persona 跨层一致**：Identity/Contract/Dialogue/Embodiment 一致为 POST_ARCHON_QUEST；god 校准与原"有度"契约一致，未把旧 Mask 放回来。
- **Persistence/migration**：`_MIGRATIONS` 每个 `ALTER TABLE ADD COLUMN` 用 `try/except OperationalError: pass`，**idempotent**（第二次启动列已存在则跳过，不会重复 ALTER 或炸）。fixture 已固定时间戳，可复现。
- **CharFrame privacy**：to_dict 不泄漏 raw window title/keyboard/prompt/memory dump/secret（测试 + 集成长跑 leak=None）。

---

## 8. 修复建议汇总（按优先级）

| 类别 | 项 | 建议动作 | 是否解冻 |
|---|---|---|---|
| BLOCKER | B1 MemoryStore 跨线程 | `check_same_thread=False` + 写锁 + 补后台线程测试 | **是**（最小） |
| SHOULD_FIX | S1 关系双写入 | 统一到 RelationshipEngine.apply | closeout 修 |
| SHOULD_FIX | S2 防重复 4 层重叠 | 收敛到 1 个主入口 | closeout 修（保守） |
| SHOULD_FIX | S4 body_snapshot 公开 | 标记 deprecated | closeout 修 |
| ACCEPTED | S3 identity 双 appraise | 保留，未来缓存 | 否 |
| ACCEPTED | 其余 §5 | 写进 freeze 声明 | 否 |

---

## 9. 结论

- **BLOCKER：1 项（MemoryStore 跨线程访问）** —— 这是真正值得解冻的最小修复，因为它导致
  **LifeBrain 三脑高层决策在运行时被静默降级**（每次决策都吞异常回退本地），且被"空 DB + 单线程测试"完美掩蔽。
- **未发现**：需要推翻后端的结构错误；EventBus 反馈环；dt 时间语义错误；LLM 职责漂移；DB migration 会炸；persona 跨层漂移；Frame 隐私泄漏。
- **整体架构**：值得冻结。各层因果实验扎实，唯一系统性缺陷是**线程 + 持久化**这一个点。
- **预期修复代价**：B1 是 ~5 行代码 + 1 条测试；S1-S4 是 closeout 清理（不改变行为语义）。

**下一步建议**：仅就 B1 做最小解冻修复（`check_same_thread=False` + `threading.Lock` + 后台线程测试），
然后 S1/S2/S4 视情况在同一个 closeout 里做保守清理，其余写入 `BACKEND_FREEZE.md` 的 accepted debt。
修复后回到 **BACKEND RC1 / FINAL FREEZE**。
