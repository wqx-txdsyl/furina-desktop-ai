"""行为包：Utility AI + 行为状态机（plan/3）+ Behavior Resolver（Activity→视觉状态）+ Motivation。"""
from .behavior_types import BehaviorDefinition, BehaviorResult, BehaviorState
from .behavior_engine import BehaviorEngine, ALLOWED_INTENTS
from .resolver import BehaviorProfile, BEHAVIOR_PROFILES, profile_for, derive_visual_state
from .motivation import BehaviorMotivation, Candidate, Personality

__all__ = [
    "BehaviorDefinition",
    "BehaviorResult",
    "BehaviorState",
    "BehaviorEngine",
    "ALLOWED_INTENTS",
    "BehaviorProfile",
    "BEHAVIOR_PROFILES",
    "profile_for",
    "derive_visual_state",
    "BehaviorMotivation",
    "Candidate",
]
