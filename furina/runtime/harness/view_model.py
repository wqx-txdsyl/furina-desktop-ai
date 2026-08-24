"""Phase 13 Harness ViewModel —— 只读观察/转换，绝不写回 domain state。

ObservationAdapter：从真实 Runtime 只读快照（Needs/Emotion/Relationship/Memory/brain/agent/spatial）。
HarnessViewModel：把真实状态转换为可显示字符串。两者都不改任何领域状态。
"""
from __future__ import annotations

from typing import Any, Dict


class ObservationAdapter:
    """只读诊断适配器。允许读 Needs/Emotion/Relationship/Memory/brain 指标；禁止写。"""

    def __init__(self, app) -> None:
        self.app = app

    # ---- 只读原语 ----
    def state_snapshot(self) -> Dict[str, Any]:
        st = self.app.state.state if hasattr(self.app, "state") else None
        if st is None:
            return {}
        d = {
            "activity": getattr(getattr(st, "life", None), "activity", ""),
            "macro": getattr(getattr(getattr(st, "life", None), "macro", None), "value", ""),
            "life_reason": getattr(getattr(st, "life", None), "reason", ""),
            "emotion": getattr(getattr(st, "emotion", None), "label", ""),
            "emotion_valence": round(float(getattr(getattr(st, "emotion", None), "valence", 0.0)), 2),
            "emotion_arousal": round(float(getattr(getattr(st, "emotion", None), "arousal", 0.0)), 2),
            "mood": round(float(getattr(getattr(st, "emotion", None), "mood", 0.0)), 1),
            "user_working": bool(getattr(st, "user_working", False)),
            "user_idle_seconds": int(getattr(st, "user_idle_seconds", 0)),
        }
        needs = getattr(st, "needs", None)
        if needs is not None:
            d["needs"] = {k: round(float(getattr(needs, k, 0.0)), 1)
                          for k in ("energy", "fatigue", "hunger", "boredom", "social_need",
                                    "sleepiness", "playfulness") if hasattr(needs, k)}
        return d

    def relationship_snapshot(self) -> Dict[str, float]:
        try:
            rel = self.app.relationship.state if hasattr(self.app, "relationship") else None
        except Exception:
            rel = None
        if rel is None:
            return {}
        out = {}
        for k in ("trust", "comfort", "annoyance", "familiarity", "interaction_tolerance",
                  "social_confidence", "intimacy"):
            v = getattr(rel, k, None)
            if isinstance(v, (int, float)):
                out[k] = round(float(v), 3)
        return out

    def brain_metrics(self) -> Dict[str, Any]:
        try:
            sched = self.app._sched if hasattr(self, "app") and hasattr(self.app, "_sched") else None
        except Exception:
            sched = None
        if sched is None:
            return {}
        return {
            "life_failures": int(getattr(sched, "_life_failure_count", getattr(sched, "_life_failures", 0)) or 0),
            "life_fallbacks": int(getattr(sched, "_life_fallback_count", getattr(sched, "_life_fallbacks", 0)) or 0),
            "life_successes": int(getattr(sched, "_life_brain_success_count", 0) or 0),
        }

    def memory_info(self) -> Dict[str, Any]:
        try:
            cnt = len(self.app.memory.store.query(limit=1, status=None)) if hasattr(self.app, "memory") else 0
        except Exception:
            cnt = 0
        return {"rows": cnt}

    def model_status(self) -> Dict[str, Any]:
        out = {"life": "n/a", "dialogue": "n/a", "agent": "idle"}
        try:
            lb = self.app.life_brain
            out["life"] = "glm" if lb is not None else "fallback-local"
        except Exception:
            pass
        try:
            db = self.app.dialogue_brain
            out["dialogue"] = "glm" if db is not None else "fallback"
        except Exception:
            pass
        try:
            from furina.agent.runtime import AgentRuntime
            out["agent"] = "ready"
        except Exception:
            pass
        return out


class HarnessViewModel:
    """把 ObservationAdapter 的原始快照转换为 UI 显示字符串。只读变换。"""

    def __init__(self, adapter: ObservationAdapter) -> None:
        self.adapter = adapter

    def status_badges(self) -> Dict[str, str]:
        model = self.adapter.model_status()
        brain = self.adapter.brain_metrics()
        life = "glm ✓" if model["life"] == "glm" else ("FALLBACK" if brain.get("life_fallbacks", 0) else "local")
        return {
            "backbone": "BACKEND RC1",
            "life": life,
            "dialogue": ("glm ✓" if model["dialogue"] == "glm" else "FALLBACK"),
            "agent": ("Agent ✓" if model["agent"] != "idle" else "Agent id"),
            "live": "● LIVE",
        }

    def current_life(self) -> Dict[str, str]:
        s = self.adapter.state_snapshot()
        rel = self.adapter.relationship_snapshot()
        body = self._body_semantic()
        spatial = self._spatial()
        brain = self.adapter.brain_metrics()
        fallback = "YES" if (brain.get("life_fallbacks") or 0) > 0 else \
                   ("FAIL" if (brain.get("life_failures") or 0) > 0 else "NO")
        return {
            "activity": s.get("activity", ""),
            "brain": self.adapter.model_status().get("life", ""),
            "fallback": fallback,     # §1：真实指标，非硬编码
            "emotion": f"{s.get('emotion','')} / {s.get('mood',0)}",
            "relationship": (f"trust {rel.get('trust',0):.2f} | comfort {rel.get('comfort',0):.2f} | "
                             f"annoy {rel.get('annoyance',0):.2f}"),
            "body": body,
            "spatial": spatial,
        }

    def _body_semantic(self) -> str:
        try:
            frame = self.adapter.app._sched.current_frame() if hasattr(self.adapter.app, "_sched") else None
            if frame:
                b = frame.get("body", {})
                return f"{b.get('posture','') } | {b.get('expression','')} | {b.get('gaze','')}"
        except Exception:
            pass
        return ""

    def _spatial(self) -> str:
        try:
            sp = getattr(self.adapter.app, "_spatial", None)
            if sp is not None:
                st = sp.state
                return f"{st.state} | x:{int(st.position.x)} y:{int(st.position.y)}"
        except Exception:
            pass
        return ""

    def conversation_display(self, messages: list) -> str:
        return "\n".join(f"{role}: {text}" for role, text in messages)
