# Phase 01 — Runtime Bootstrap / Selfcheck / Failure Visibility Hardening

> **RECOVERY_STATUS:** `RECONSTRUCTED`
>
> **Phase:** `Phase 01`
>
> **Confidence:** `MEDIUM-HIGH`
>
> **说明：** 当前没有找回这份任务书的逐字原件。本文件依据后续代码、阶段报告、原始 `plan/` 文档与已恢复的后续任务书反向重建。
> 它用于恢复“当时模型应执行的任务约束”，**不冒充历史原文**。如果未来找到原件，应保留本文件并新增原件，不能用原件静默覆盖重建稿。
>
> **主要依据：**
- `PHASE_PLAN.md — M0`
- `plan/0 main plan.md`
- `tests/test_skeleton.py`
- `main.py`

---

## 1. 背景

骨架存在不等于真实可运行。本轮只处理启动链、自检和错误可见性。

## 2. 必须检查

- `main.py` 正常启动与 CLI 参数是否共用同一配置入口。
- EventBus 初始化顺序是否确定。
- State / Runtime / Window 的构造是否存在循环依赖。
- `.env` / LLM provider 缺失是否安全降级。
- 数据目录、数据库路径、素材目录不存在时是否给出清晰错误或安全创建。
- GUI smoke 是否真的创建 QApplication/Window，而不是只 import。

## 3. 要求

- 自检输出必须区分 `OK / DEGRADED / FAILED`。
- 禁止“捕获所有异常然后继续”导致 false-green。
- 每个核心子系统至少有一个最小健康检查。
- CLI smoke 不得改用户持久数据。

## 4. 验收

```text
python main.py --selfcheck
python main.py --smoke
python -m pytest tests/test_skeleton.py
```

均应稳定完成；任何失败必须可定位到具体子系统。

## 5. 非目标

不改变后续系统语义；不优化视觉；不增加新 LLM。
