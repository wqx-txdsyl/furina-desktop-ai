# Phase 22 — Voice Interaction
# Master Plan — EXACT

## 0. Existing foundation

The existing conversation, character, event and runtime-frame systems provide text-level meaning
and presentation state. Production microphone capture, ASR, TTS, turn-taking and speech animation
remain a separate phase and must not create another response owner.

## 1. Goal

Deliver understandable, interruptible and privacy-visible live voice interaction while preserving
one conversation truth, one speaking owner and deterministic fallback to text.

## 2. Invariants

- No covert or ambiguous microphone capture; listening state is always visible and user-controlled.
- Push-to-talk and immediate stop are available; permission denial degrades cleanly to text.
- Raw audio is bounded and non-durable by default; diagnostics never contain recoverable speech.
- User speech and emergency stop outrank character speech; interruption is deterministic.
- One response turn has one authoritative mouth/audio owner; retries cannot double-speak.
- The selected voice has documented legal and product-use status; no unsupported cloning claim.
- ASR/TTS confidence or fluency never constitutes task verification.

## 3. Delta order

```text
22A Audio Device & Privacy Boundary
→ 22B Speech Recognition & Push-to-Talk
→ 22C Speech Synthesis & Voice Profile
→ 22D Streaming, Barge-in & Turn-taking
→ 22E Speech Animation & Single-Mouth Integration
→ 22F Live Voice Final Gate
```
