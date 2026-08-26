# Phase 10 Recovery Manifest

## Recovery rule

- `EXACT_RECOVERED`：找回了当时生成/保存的任务书文件，内容原样复制；仅文件名前加排序/EXACT 标识时不改正文。
- `RECONSTRUCTED`：没有找到逐字原件，依据后续可验证资料恢复任务要求；正文顶部明确声明，不冒充原文。
- 将来找到更多原件时：**新增，不覆盖，不删除重建稿。**

## Sources used

- `docs/BACKEND_FREEZE.md`
- `docs/FURINA_BACKEND_AUDIT.md`
- `FURINA_RC1_CLOSEOUT_REPORT.md`
- `furina/runtime/frame.py`

## Files

| File | Status |
|---|---|
| `01_CHARACTER_RUNTIME_FRAME_CONTRACT_RECONSTRUCTED.md` | RECONSTRUCTED |
| `02_BACKEND_FREEZE_FULL_AUDIT_RECONSTRUCTED.md` | RECONSTRUCTED |
| `03_RC1_BACKEND_CLOSEOUT_RECONSTRUCTED.md` | RECONSTRUCTED |
