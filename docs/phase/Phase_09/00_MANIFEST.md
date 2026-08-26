# Phase 09 Recovery Manifest

## Recovery rule

- `EXACT_RECOVERED`：找回了当时生成/保存的任务书文件，内容原样复制；仅文件名前加排序/EXACT 标识时不改正文。
- `RECONSTRUCTED`：没有找到逐字原件，依据后续可验证资料恢复任务要求；正文顶部明确声明，不冒充原文。
- 将来找到更多原件时：**新增，不覆盖，不删除重建稿。**

## Sources used

- `docs/FURINA_EMBODIMENT_REPORT.md`
- `furina/embodiment`
- `tests/test_embodiment.py`
- `BACKEND_FREEZE.md`

## Files

| File | Status |
|---|---|
| `01_EMBODIED_EXPRESSION_ENGINE_RECONSTRUCTED.md` | RECONSTRUCTED |
| `02_BODY_VALIDATOR_AND_CONFLICT_RULES_RECONSTRUCTED.md` | RECONSTRUCTED |
| `03_EMBODIMENT_CLOSEOUT_RECONSTRUCTED_FROM_REPORT.md` | RECONSTRUCTED |
