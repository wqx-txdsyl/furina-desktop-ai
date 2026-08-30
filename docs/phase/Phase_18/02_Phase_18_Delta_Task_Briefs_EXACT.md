# Phase 18 — Delta Task Briefs — EXACT

## 18A — Computer-Control Protocol & Windows Target Identity

Define a closed adapter protocol for inspect/action/result/cancel; exact window/process/control
identity; foreground/focus proof; bounded observations; action idempotency; capability mapping and
Phase 16 approval hooks. Reuse Application Catalog. Tests must include focus theft, stale handles,
PID/window reuse, DPI/multi-monitor, cancellation, secret redaction and zero side effects on deny.

No broad automation feature is implemented until 18A receives Reviewer acceptance.

## 18B — Browser DOM & Accessibility

Implement a real supported browser adapter with tab/frame/origin identity, DOM/accessibility
snapshots, navigation/download/upload/form actions, reconnect and cancellation. Cross-origin,
download destination, file picker, clipboard and credential fields require explicit policy.
Visual fallback remains disabled here.

Tests: stale DOM, navigation race, wrong tab/frame, popup, download tamper, upload path escape,
password fields, hostile page text, bounded snapshot and real harmless browser UAT.

## 18C — Files, Office & PDF Workflows

Prefer document-native libraries and official object models. Implement create/read/edit/export for
Word-compatible documents, spreadsheets, presentations and PDFs with stable input/output
snapshots, atomic writes, backup/overwrite approval and render-based verification where layout
matters. Never automate Office solely by blind keystrokes when a structured path exists.

Tests: format round-trip, formulas, layout/render comparison, locked files, overwrite denial,
macro/external-link safety, malformed input, cancellation, recovery and independent artifact
verification.

## 18D — Mail, Calendar & Development Tools

Implement provider-first mail/calendar operations and governed delegation to VS Code, terminal or
Coding Agent. Draft is distinct from send; recipient/calendar identity and final payload are
rechecked immediately before the side effect. Terminal/coding delegation inherits WorkContract
scope and cannot recursively widen authority.

Tests: wrong-recipient prevention, stale draft, attachment identity, timezone/DST, duplicate event,
late cancellation, terminal scope escape, delegated result verification and real provider UAT.

## 18E — Cross-Application Workflow Gate

Run production workflows equivalent to:

```text
retrieve bounded input
→ transform in document/spreadsheet
→ create verified report
→ prepare destination draft
→ obtain final approval
→ perform side effect exactly once
```

Audit all computer-control call sites, full owner/permission/verification traces, restart at every
side-effect boundary, Windows UI responsiveness and three full suites. Gate branch is evidence-only.
