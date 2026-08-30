# Phase 18 — Computer Control & Office Automation
# Master Plan — EXACT

## 0. Evidence baseline

Current repository evidence already includes Capability Registry, Application Catalog, filesystem
and document tools, browser/open-url and screenshot foundations, Communication/Calendar interfaces
and Phase 16 governed execution. Browser DOM automation and broad desktop control are explicitly
unavailable; this Phase must not relabel foundations as completed adapters.

## 1. Goal

Complete bounded, inspectable workflows across browser, Windows applications, files, Office,
email/calendar and development tools. Acceptance is an end-to-end outcome with independent
verification, not a screenshot or a successful click.

## 2. Control preference

```text
official API / provider
→ document-native library or application object model
→ browser DOM / accessibility
→ Windows UI Automation
→ bounded visual pointer/keyboard fallback
```

Fallback may never silently reduce identity, destination, approval or verification strength.

## 3. Invariants

- every action binds contract/run/tool/capability/target identity;
- read and write capabilities remain distinct;
- irreversible send/delete/publish/overwrite requires approval at the real side-effect boundary;
- password/payment/private-window surfaces fail closed;
- focus/window changes cannot redirect input to another target;
- downloads/uploads use stable path, content and provenance checks;
- no output text bypasses Single Mouth;
- all adapters support cancellation, timeout and bounded observations.

## 4. Delta order

```text
18A Computer-Control Protocol & Windows Target Identity
→ 18B Browser DOM/Accessibility
→ 18C Files, Office & PDF Workflows
→ 18D Mail, Calendar & Development Tools
→ 18E Cross-Application Workflow Gate
```

## 5. Live acceptance

Controlled Windows UAT must prove at least one browser workflow, one Office/document workflow and
one multi-application workflow with a meaningful independently verified artifact. Mocks cannot
close the Phase.
