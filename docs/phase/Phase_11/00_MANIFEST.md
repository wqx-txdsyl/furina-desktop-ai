# Phase 11 Recovery Manifest

## Recovery rule

- `EXACT_RECOVERED`：找回了当时生成/保存的任务书文件，内容原样复制；仅文件名前加排序/EXACT 标识时不改正文。
- `RECONSTRUCTED`：没有找到逐字原件，依据后续可验证资料恢复任务要求；正文顶部明确声明，不冒充原文。
- 将来找到更多原件时：**新增，不覆盖，不删除重建稿。**

## Sources used

- `docs/FURINA_PHASE11_REPORT.md`
- `BACKEND_FREEZE.md`
- `furina/runtime/frontend.py`
- `furina/runtime/animation.py`

## Files

| File | Status |
|---|---|
| `01_FRONTEND_CHARACTER_RUNTIME_RECONSTRUCTED.md` | RECONSTRUCTED |
| `02_PHASE11_STEP0_CONTRACT_CLEANUP_RECONSTRUCTED.md` | RECONSTRUCTED |
| `03_PHASE11_SCENE_ASSET_GATE_RECONSTRUCTED.md` | RECONSTRUCTED |
