# Phase 22 — Delta Task Briefs — EXACT

## 22A — Audio Device & Privacy Boundary

Implement explicit device selection, permissions, visible listening/speaking indicators,
push-to-talk, mute, emergency stop, bounded buffers and cleanup. Define retention and redaction
rules. Prove denied/revoked devices and device changes fail safely without hidden capture.

## 22B — Speech Recognition & Push-to-Talk

Add bounded ASR with endpointing, language/profile selection, partial/final transcript distinction,
confidence handling and correction UI. Only finalized user-approved input enters normal conversation
semantics. Test noise, silence, cancellation, offline/provider failure and sensitive speech paths.

## 22C — Speech Synthesis & Voice Profile

Implement a legally usable Furina voice profile, normalized pronunciation, chunking, caching policy,
volume/rate controls and text fallback. Secrets and hidden tool payloads must never be spoken or
cached. Provider outage and rate limit must not duplicate utterances.

## 22D — Streaming, Barge-in & Turn-taking

Integrate streaming ASR/TTS with the conversation turn ledger. Define who owns listen, think and
speak states, cancellation propagation, user barge-in and stale-output rejection. Prove retries,
late chunks and reconnects cannot create two active turns.

## 22E — Speech Animation & Single-Mouth Integration

Drive Phase 20/21 speech animation through CharacterRuntimeFrame references only. Audio timing may
animate the mouth but may not write character or task truth. Stop/cancel immediately closes both
audio and animation, including late callbacks.

## 22F — Live Voice Final Gate

Run real-device Windows UAT across supported microphones/speakers, privacy and retention audit,
latency/intelligibility checks, interruption stress, long conversation soak, single-mouth proof and
three full suite runs. Fixes require reviewed micro-patches.
