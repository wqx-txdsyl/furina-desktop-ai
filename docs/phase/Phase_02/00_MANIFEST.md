# Phase 02 Recovery Manifest

## Recovery rule

- `EXACT_RECOVERED`：找回了当时生成/保存的任务书文件，内容原样复制；仅文件名前加排序/EXACT 标识时不改正文。
- `RECONSTRUCTED`：没有找到逐字原件，依据后续可验证资料恢复任务要求；正文顶部明确声明，不冒充原文。
- 将来找到更多原件时：**新增，不覆盖，不删除重建稿。**

## Sources used

- `PHASE_PLAN.md — M1 / M1.5`
- `plan/2 asset engine.md`
- `data/assets/manifest.json`
- `tests/test_assets.py`
- `tests/test_animation.py`

## Files

| File | Status |
|---|---|
| `01_ASSET_ENGINE_MANIFEST_RESOLVER_RECONSTRUCTED.md` | RECONSTRUCTED |
| `02_ASSET_GENERATION_QC_PIPELINE_RECONSTRUCTED.md` | RECONSTRUCTED |
| `03_MULTIFRAME_ANIMATION_M1_5_RECONSTRUCTED.md` | RECONSTRUCTED |
