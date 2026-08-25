# Furina Canon Life — Source Map（C2 数据来源地图）

> C2（Canon Life History）的逐阶段来源登记。C2 不是剧情百科，是"经历及其现在影响"。
> 本 Phase 只使用**当前仓库已有** Canon Evidence / Persona Model 作为 TIER 0 种子
> （docs/persona/FURINA_CANON_EVIDENCE.md，FUR-001~056，已人工筛过的 provenance seed），
> **不联网脑补剧情**。资料不足的阶段标记 `status=PARTIAL`，不得猜。

## 阶段覆盖（15 段）

| # | 阶段 | quest/act | 状态 | 主要 Evidence IDs |
|---|---|---|---|---|
| 01 | ORIGIN / FOCALORS SEPARATION | 主线 Chapter IV（4.2 揭示） | COMPLETE（seed） | FUR-048, FUR-041, FUR-042 |
| 02 | PUBLIC ROLE BEGINNING | 主线前史 | COMPLETE（seed） | FUR-050, FUR-048 |
| 03 | LONG PUBLIC HYDRO ARCHON ROLE | 五百年在位 | COMPLETE（seed） | FUR-049, FUR-037 |
| 04 | DAILY PUBLIC PERFORMANCE | 在位期 | COMPLETE（seed） | FUR-001, FUR-002, FUR-003, FUR-004, FUR-005, FUR-031 |
| 05 | PRIVATE ISOLATION / MASK PRESSURE | 在位期私下 | COMPLETE（seed） | FUR-037, FUR-038, FUR-049 |
| 06 | FONTAINE ARCHON QUEST ACT I | Chapter IV Act I | PARTIAL | FUR-006（庭审相关语境） |
| 07 | ACT II | Chapter IV Act II | PARTIAL | FUR-006, FUR-007 |
| 08 | ACT III | Chapter IV Act III | PARTIAL | FUR-007, FUR-008 |
| 09 | ACT IV | Chapter IV Act IV | PARTIAL | FUR-008, FUR-039 |
| 10 | ACT V — TRIAL / REVELATION / END | Chapter IV Act V（4.2） | COMPLETE（seed） | FUR-041, FUR-042, FUR-043, FUR-048, FUR-049, FUR-050, FUR-051, FUR-006, FUR-008, FUR-039 |
| 11 | POST-AQ EARLY LIFE | 主线后 | COMPLETE（seed） | FUR-053, FUR-054 |
| 12 | STORY QUEST I（水的女儿） | 传说任务第一幕 | COMPLETE（seed） | FUR-019, FUR-055 |
| 13 | VISION / RETURN TO STAGE | 传说任务结尾 | COMPLETE（seed） | FUR-044, FUR-055, FUR-015 |
| 14 | ORDINARY LIFE | 现状 | COMPLETE（seed） | FUR-025, FUR-027, FUR-028, FUR-029, FUR-056 |
| 15 | LATER OFFICIAL FURINA APPEARANCES | 后续官方出场 | PARTIAL（仅仓库可见证据） | FUR-022, FUR-023, FUR-024, FUR-045, FUR-046, FUR-047 |

## 逐条目登记

| SOURCE_ID | SOURCE_TYPE | ACCESS_SOURCE | ORIGINAL_MATERIAL | CANON_TIER | VERSION | QUEST | ACT | SCENE | FURINA_PRESENT | RELEVANCE | EVIDENCE_IDS | NOTES |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-001 | CURATED_EVIDENCE | repo: docs/persona/FURINA_CANON_EVIDENCE.md | 游戏内简体中文正式文本（角色故事/语音/主线/传说任务） | TIER 0 | 56 units (FUR-001~056) | Chapter IV + 传说任务"水的女儿" | I–V | 全 | 是 | C2 全阶段种子 | FUR-001~056 | 已人工筛过的 provenance seed；本 Phase 唯一 factual 来源 |
| SRC-002 | CURATED_MODEL | repo: docs/persona/FURINA_PERSONA_MODEL.md | 从 Evidence 派生的统一人格模型 | TIER 0（派生） | 118 行 | — | — | 全 | 是 | C2 psychological/present-day 推导 | 见 §9 traceability | 用于 psychological_effects/present_day_effects 的结构化推导 |
| SRC-003 | CURATED_MODEL | repo: furina/persona/furina_canon.py | Canon 常量（IDENTITY_FACTS/PERSONALITY_AXES/CORE_CONTRADICTIONS） | TIER 0（派生） | 342 行 | — | — | 全 | 是 | C1/C2 运行时权威 | FUR-015~044 | runtime 唯一 Canon 源 |
| SRC-004 | OFFICIAL_GAME_TEXT | 不在 repo 直接保存（evidence doc 已概括；禁止大段复制原文） | 主线 Chapter IV Act I–V 中文原文 | TIER 0 | — | Chapter IV | I–V | 庭审/歌剧院/独处 | 是 | Act V 终局 | FUR-006/007/008/039/041/042/043/048/049/050/051 | 本 Phase 不复制大段台词；evidence doc 已保留 ≤15 字 snippet |
| SRC-005 | OFFICIAL_GAME_TEXT | 不在 repo 直接保存 | 传说任务"水的女儿"中文原文 | TIER 0 | — | 传说任务 | I | 结尾神之眼 | 是 | CHOSEN_PERFORMANCE 锚点 | FUR-019, FUR-055 | 同上 |
| SRC-006 | OFFICIAL_GAME_TEXT | 不在 repo 直接保存 | Character Stories 1–5 / Vision / Character Details / Voice-Over 中文原文 | TIER 0 | — | — | — | 全 | 是 | C2 长时段证据 | FUR-001~005, 009~018, 020~040, 044~047, 052~056 | 同上 |
| SRC-007 | OFFICIAL_WEB | HoYoWiki Furina 官方角色页（cross-check 预留） | 官方角色资料 | TIER 1 | — | — | — | — | 是 | 身份/时间顺序交叉核验 | — | 本 Phase 未联网取用；标记为交叉核验入口 |
| SRC-008 | OFFICIAL_MEDIA | 官方 Character Demo/Teaser/Story Teaser/Cutscene/trailers（cross-check 预留） | 官方视频 | TIER 1 | — | — | — | — | 是 | 场景语境补全 | — | 本 Phase 未联网取用 |
| SRC-009 | COMMUNITY_MIRROR | 社区 Wiki（biligame/萌娘百科等，仅定位/交叉核验，不升级为 TIER 0） | 官方游戏文本的社区镜像 | TIER 2 | — | — | — | — | 是 | 定位文本/补完整上下文 | — | 本 Phase 未取用；如未来使用必须标 access_source=COMMUNITY_MIRROR, original_material=OFFICIAL_GAME_TEXT |
| SRC-010 | FORBIDDEN | Reddit/论坛/MBTI/知乎人格分析/短视频/二创/同人/AI summary | 非官方解读 | TIER 3 | — | — | — | — | — | **禁止** | — | 绝不进入 CanonEpisode factual fields |

## C2 数据文件

- `data/canon/furina_life_history.json` —— 20+ 条 CanonEpisode（version-controlled、只读）。
- `data/canon/furina_life_sources.json` —— 上述 SOURCE_ID 机器可读登记。

## 验收计数（C2 ACCEPTANCE）

- canon_source_map_entries: 10（SRC-001~010）
- canon_episode_count: 20
- tier0_sources: SRC-001~006（evidence doc + 官方游戏文本/角色资料，经 curated seed）
- tier1_sources: SRC-007, SRC-008（cross-check 预留，本 Phase 未联网取用）
- tier2_mirror_sources: SRC-009（未取用）
- unsupported_sources_excluded: SRC-010（TIER 3 禁止）
- runtime_canon_mutable = false
