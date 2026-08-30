# Phase 19 — Delta Task Briefs — EXACT

## 19A — Channel, Contact & Destination Contract

Create provider-qualified ChannelId/AccountId/ContactId/ConversationId/DestinationSnapshot,
capability vocabulary, inbound provenance, bounded attachment references, draft/send split,
idempotency keys, rate limits, cancellation and secret handling. Duplicate names, account switches,
stale conversations and destination mutation fail closed.

## 19B — Enterprise Providers

Implement selected official APIs such as DingTalk/Feishu/WeCom only when credentials and test
tenants are available. Support bounded receive/search/draft/send and attachments according to each
platform. Verify scopes and destination immediately before send. Mocks supplement but do not
replace real provider UAT.

## 19C — Consumer Desktop Channels

For WeChat/QQ or similar clients, use supported/controlled desktop automation under Phase 18.
No protocol reverse engineering, risk-control bypass, mass messaging, covert background send or
fake presence. Unsupported states are explicit. Require visible account/conversation proof and
final-send approval.

## 19D — Media & Content Services

Add bounded media playback/control and content browsing/draft/reminder adapters. Publishing,
commenting, liking, following or continuous-interaction actions are separate high-risk
capabilities and must comply with platform rules. Do not implement engagement farming.

## 19E — Unified Inbox, Product UI & Final Gate

Build a bounded unified inbox/control surface with source identity, notification policy, draft
review, approval state and emergency stop. Prove notification coalescing, direct-user priority,
cross-account isolation, restart idempotency, exactly-once send, Single Mouth and real UAT.
Run complete suite three times; gate branch is evidence-only.
