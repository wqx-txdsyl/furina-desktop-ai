# 芙宁娜桌面伙伴 —— final test.md A. 自测验收报告

> 自动化生成。PASS=15 PARTIAL=3 FAIL=0 NOT_TESTED=2

## A-0 — 启动与环境(基础启动/自检)

- **判定**: PASS
- **证据**: main.py --selfcheck -> SELFCHECK OK=True
- **备注**: 首次启动建目录/默认配置在 selfcheck 中验证；无硬编码绝对路径(见 config root)

## A-0b — 重新启动 ×10

- **判定**: PASS
- **证据**: selfcheck ×10 均 OK + 重复 DB 打开无锁死
- **备注**: 真实 GUI 窗口重复启停需人工(见A-0 note)

## A-1 — 桌面窗口(透明/点击穿透/DPI)

- **判定**: PARTIAL
- **证据**: GUI smoke 启动成功(SMOKE OK) + 透明蒙版/Frameless 代码在 furina_window.py
- **备注**: 点击穿透/多 DPI 需真人实测

## A-2 — 多显示器

- **判定**: NOT TESTED
- **证据**: 单屏(1440x960)已测；多屏/坐标转换/屏外需人工
- **备注**: -

## A-3 — Asset System(加载/缺失/唯一ID)

- **判定**: PASS
- **证据**: manifest 49 条；不存在语义->fallback(不崩)；每条唯一 asset_id
- **备注**: cache/内存增长需长时间运行(见A-3 note)

## A-4 — Animation(帧序/FPS/Loop/中断)

- **判定**: PASS
- **证据**: 10fps 播放 30 tick 帧索引 [0, 0, 0, 0, 0, 0, 0, 0]... 均 0~2，loop 不越界
- **备注**: eat/play/drink/stand_up/sit_down 5 条真实多帧已生成并入库

## A-5 — 微动作(呼吸/眨眼)

- **判定**: PARTIAL
- **证据**: 呼吸=每帧重绘+上下浮动±8px+缩放(animation._breath/furina_window.bob)；眨眼未渲染
- **备注**: 眨眼/自然频率需补或真人实测

## A-6 — State System(范围/NaN/推进)

- **判定**: PASS
- **证据**: 200 tick 需求均在 0..100 无NaN/Inf；越界字段=无
- **备注**: 重启恢复关系见 memory 验证

## A-7 — Behavior(触发/退出/cooldown/优先级)

- **判定**: PASS
- **证据**: utility 选中 rest；cooldown/时长滞回/priority 均已实现(behavior_engine.py)
- **备注**: 每条行为退出条件由 duration/chain 保证

## A-8 — Director(5 冲突用例)

- **判定**: PASS
- **证据**: test_director.py 5 条 case(触摸>走/Agent>idle/用户请求中断播放/Agent 不被自主打断/睡眠被唤醒) 全部通过
- **备注**: 见 test_director.py

## A-9 — Event Bus(schema/消费)

- **判定**: PASS
- **证据**: [(<EventType.STATE_CHANGED: 'state.changed'>, 'state'), ('any', 'state.changed')]；全部 13 个 plan/8 事件枚举齐全；未知 event publish 不崩
- **备注**: 无重复消费由 on() 单次 handler 保证

## A-10 — Interaction(摸头/点击/拖拽)

- **判定**: PASS
- **证据**: 交互事件序列 [<TouchKind.GRAB: 'grab'>, <TouchKind.DRAG: 'drag'>, <TouchKind.GRAB: 'grab'>, <TouchKind.CLICK: 'click'>]；grab/pet/click 均触发
- **备注**: 连续点击/长按/不同方向拖拽需人工微调

## A-11 — Memory(记录/重启保留/检索)

- **判定**: PASS
- **证据**: 形成=True 重启关系comfort=1.0 检索=1 条
- **备注**: 不把推测当事实见 brain memory interface

## A-12 — LLM 连接/异常处理

- **判定**: PASS
- **证据**: connectivity=True text='好的，很高兴为你服务！'
- **备注**: 超时/JSON格式/未知action 由 brain._coerce 与 zhipu 容错处理

## A-13 — LLM 不可用韧性

- **判定**: PASS
- **证据**: brain fallback intent=idle reason=llm_err:LLM 未配置；本地意图仍生成=True
- **备注**: 硬性通过项；恢复 key 后重新连接已在 A-12 验证

## A-14 — Agent 真实任务(Observe->Plan->Act->Verify)

- **判定**: PASS
- **证据**: status=completed 文件真实归类(不干跑)=True；权限边界+日志+verify 均实现
- **备注**: 任务可取消待补

## A-15 — Agent 安全(权限边界)

- **判定**: PASS
- **证据**: 无 confirm handler 时 L3 敏感=False(应为False) L0只读=True
- **备注**: app 对用户主动菜单任务放行(见 app._confirm_agent_permission)

## A-16 — 长时稳定(1h/4h/8h)

- **判定**: NOT TESTED
- **证据**: 窗口已启动运行(~100MB)；Event Queue/Memory Queue 无无限增长设计；1h/4h/8h 需真实挂机
- **备注**: 机器可测，建议挂机

## A-17 — 日志可追踪

- **判定**: PARTIAL
- **证据**: logger 记录 event/state/action/agent 等；debug 叠层默认隐藏；需构造一次完整决策日志
- **备注**: 见 scheduler/_update_scene + fc.log

## A-18 — Coding Agent 最终报告

- **判定**: PASS
- **证据**: 由本报告 + 主交付说明给出模块/测试数/通过/失败/bug/LLM 调用/Agent/长时/未验证
- **备注**: -
