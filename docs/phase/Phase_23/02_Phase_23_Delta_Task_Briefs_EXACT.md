# Phase 23 — Delta Task Briefs — EXACT

## 23A — Capture, Consent & Privacy Contract

Implement selected-window/region capture, visible indicators, permission revocation, sensitive-surface
classification, masking, resolution/rate/byte ceilings and deterministic disposal. Bind captures to
stable target identities. Prove stale or wrong-window pixels are rejected.

## 23B — Accessibility Fusion & OCR

Fuse Phase 18 accessibility/DOM facts with bounded OCR while retaining separate provenance and
confidence. Prefer structure when available, detect disagreement and expose uncertainty. Test mixed
DPI, language, zoom, occlusion, dynamic content and adversarial text-in-image cases.

## 23C — UI, Image, Chart & Document Understanding

Add typed observations for layout, icons, images, charts and document regions. Bound provider
inputs/outputs and label inference explicitly. Unsupported or ambiguous content stays inconclusive;
no fabricated values, hidden OCR or automatic verification.

## 23D — Deictic Reference & Spatial Grounding

Resolve phrases such as “这个窗口/这里/左边那张图” against a timestamped scene and cursor/selection
context. Ambiguous candidates require clarification. Grounding expires on window, geometry, content
or focus change and cannot silently retarget an action.

## 23E — Observation Replay & Evidence Separation

Create privacy-safe replay metadata and deterministic observation envelopes without retaining raw
captures by default. Keep observation, interpretation, proposed action, execution result and Phase
16 verification as distinct layers. Redact all exports and diagnostics.

## 23F — Privacy/Multimodal Final Gate

Run consent/revocation, sensitive-surface, stale-target, prompt-injection, OCR disagreement,
grounding ambiguity, provider-failure and resource-bound adversarial tests plus real Windows UAT.
Complete the privacy review and three full suite runs. No installer or release work is accepted here.
