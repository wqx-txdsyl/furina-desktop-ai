"""Embodied Expression Engine（Phase 09）—— 把内部状态确定性投影到身体（semantic intents）。

输入（全部冻结/由外部算好）：
    emotion_label / PersonaMode / RelationshipState / Activity / SpeechIntent /
    WorldState(factors) / Needs(fatigue) / CharacterAppraisal
输出：BodyExpressionState（表情/视线/姿态/开放度/距离/节奏/幅度/犹豫/克制/微动作/过渡/口语同步 + reasons）。

关键原则：
  - 确定性：0 次 LLM 调用。Body 不解释 Memory（Memory 已通过 emotion/mode/关系影响当前状态）。
  - Activity 是最高的语义约束：读取/睡觉/吃/工作必须尊重身体可行性。
  - Fatigue 能覆盖 proud/performative（不能因为"有气场"突然精神百倍）。
  - Emotion 不只改脸：必须同时改 gaze / tempo / amplitude / hesitation / composure。
  - Silence 不等于冻结：speech=None 时仍有自然生命表现。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from furina.dialogue import PersonaMode, ExpressionStrategy, SpeechIntent, DialogueAct
from furina.persona.character_identity import CharacterAppraisal
from .model import (
    BodyExpressionState, ExpressionIntent, GazeIntent, PostureIntent, ProximityIntent,
    TempoIntent, TransitionStyle, MicroMotionIntent, SpeechSync, EmbodimentPersona,
    EMBODIMENT_PERSONAS, FURINA_EMBODIMENT,
)

# ---------------------------------------------------------------- 表情基准（emotion → expression）
_EMOTION_EXPRESSION = {
    "proud": ExpressionIntent.PROUD.value,
    "happy": ExpressionIntent.PLEASED.value,
    "excited": ExpressionIntent.EXCITED.value,
    "curious": ExpressionIntent.SOFT.value,
    "calm": ExpressionIntent.NEUTRAL.value,
    "sleepy": ExpressionIntent.TIRED.value,
    "embarrassed": ExpressionIntent.EMBARRASSED.value,
    "annoyed": ExpressionIntent.ANNOYED.value,
    "sad": ExpressionIntent.SAD.value,
    "lonely": ExpressionIntent.CONCERNED.value,
    "surprised": ExpressionIntent.SOFT.value,
}


class EmbodiedExpressionEngine:
    """确定性身体表达引擎。"""

    def __init__(self, persona: Optional[EmbodimentPersona] = None) -> None:
        self.persona = persona or FURINA_EMBODIMENT

    # ------------------------------------------------------------------ public
    def express(
        self,
        *,
        emotion: str = "calm",
        mode: str = PersonaMode.CASUAL.value,
        secondary_mode: str = "",
        dialogue_act: str = DialogueAct.COMMENT.value,
        speech_intent: Optional[SpeechIntent] = None,
        relationship: Optional[Dict] = None,
        activity: str = "idle",
        world: Optional[Dict] = None,
        fatigue: float = 20.0,          # 0..100
        needs: Optional[Dict] = None,
        appraisal: Optional[CharacterAppraisal] = None,
        social_motive: float = 0.4,     # 0..1 社交渴望
        recent_rejection: bool = False,
        user_present: bool = True,
        user_working: bool = False,
        silence: bool = False,          # should_speak == False
    ) -> BodyExpressionState:
        p = self.persona
        rel = relationship or {}
        w = world or {}
        needs = needs or {}
        apt = appraisal or CharacterAppraisal()

        st = BodyExpressionState()
        reasons: List[str] = []

        # ---- 1. emotion → expression（基础表情，不等同 emotion label）
        st.expression = _EMOTION_EXPRESSION.get(emotion, ExpressionIntent.NEUTRAL.value)
        reasons.append(f"emotion_{emotion}")

        # ---- 2. PersonaMode → body（§14）
        self._apply_mode(st, mode, reasons)

        # ---- 2b. 角色身份（embodiment persona）调制—— 在共享 mode 表之上施加 persona 增量。
        # 这层是真的把人**区分开**（Current 能松 / Mask 端着），不是只换几个数字。
        self._apply_persona(st, mode, reasons)

        # ---- 4. emotion 非脸维度：gaze / tempo / amplitude / hesitation / composure
        self._apply_emotion_body(st, emotion, reasons)

        # ---- 5. relationship 调制身体距离与开放度（§7/§13/§19/§22）
        self._apply_relationship(st, rel, apt, recent_rejection, reasons)

        # ---- 6. fatigue 覆盖能量（§9）：能覆盖 proud/performative
        self._apply_fatigue(st, fatigue, reasons)

        # ---- 7. speech / silence（§26/§27）
        self._apply_speech(st, dialogue_act, speech_intent, silence, reasons)

        # ---- 8. activity 兼容（§8/§28/§29）—— 最高语义约束
        self._apply_activity(st, activity, user_working, reasons)

        # ---- 9. 社交矛盾/迟疑（§20）：想靠近但被拒 → hesitation
        self._apply_contradiction(st, apt, social_motive, recent_rejection, rel, reasons)

        # ---- 10. micro motion（§23/§24）—— 语义偏好，不调用 asset
        st.micro_motion = self._micro_preference(st, fatigue, reasons)

        # ---- 11. transition style（§30）
        st.transition_style = self._transition(emotion, mode, st, reasons)

        # ---- 12. speech_sync
        st.speech_sync = (SpeechSync.NONE.value if silence
                          else SpeechSync.ANIMATED.value if st.movement_amplitude > 0.65
                          else SpeechSync.NEUTRAL.value)
        st.reasons = reasons
        return st

    # ------------------------------------------------------------------ §14 mode → body
    def _apply_mode(self, st: BodyExpressionState, mode: str, reasons: List[str]) -> None:
        table = {
            PersonaMode.PERFORMATIVE.value: dict(posture=PostureIntent.UPRIGHT.value, openness=0.55,
                                                 amplitude=0.75, tempo=TempoIntent.LIVELY.value,
                                                 composure=0.8, gaze=GazeIntent.USER.value, transition=TransitionStyle.ENERGETIC.value),
            PersonaMode.CASUAL.value: dict(posture=PostureIntent.RELAXED.value, openness=0.65, amplitude=0.4,
                                           tempo=TempoIntent.NORMAL.value, composure=0.6, gaze=GazeIntent.AROUND.value,
                                           transition=TransitionStyle.SMOOTH.value),
            PersonaMode.GUARDED.value: dict(posture=PostureIntent.CONTAINED.value, openness=0.3, amplitude=0.3,
                                            tempo=TempoIntent.SLOW.value, composure=0.85, gaze=GazeIntent.SIDE.value,
                                            transition=TransitionStyle.HESITANT.value),
            PersonaMode.SINCERE.value: dict(posture=PostureIntent.RELAXED.value, openness=0.75, amplitude=0.25,
                                            tempo=TempoIntent.SLOW.value, composure=0.5, gaze=GazeIntent.USER.value,
                                            transition=TransitionStyle.GENTLE.value),
            PersonaMode.PROUD.value: dict(posture=PostureIntent.UPRIGHT.value, openness=0.4, amplitude=0.6,
                                          tempo=TempoIntent.NORMAL.value, composure=0.85, gaze=GazeIntent.USER.value,
                                          transition=TransitionStyle.IMMEDIATE.value),
            PersonaMode.VULNERABLE.value: dict(posture=PostureIntent.CONTAINED.value, openness=0.5, amplitude=0.2,
                                               tempo=TempoIntent.VERY_SLOW.value, composure=0.4, gaze=GazeIntent.DOWN.value,
                                               transition=TransitionStyle.GENTLE.value),
            PersonaMode.RESPONSIBLE.value: dict(posture=PostureIntent.ENGAGED.value, openness=0.55, amplitude=0.35,
                                                tempo=TempoIntent.NORMAL.value, composure=0.75, gaze=GazeIntent.USER.value,
                                                transition=TransitionStyle.IMMEDIATE.value),
            PersonaMode.PLAYFUL.value: dict(posture=PostureIntent.RELAXED.value, openness=0.7, amplitude=0.6,
                                            tempo=TempoIntent.LIVELY.value, composure=0.55, gaze=GazeIntent.AROUND.value,
                                            transition=TransitionStyle.ENERGETIC.value),
        }
        row = table.get(mode)
        if row is None:
            return
        if row.get("posture"):
            st.posture = row["posture"]
        st.body_openness = row.get("openness", st.body_openness)
        st.movement_amplitude = row.get("amplitude", st.movement_amplitude)
        st.movement_tempo = row.get("tempo", st.movement_tempo)
        st.composure = row.get("composure", st.composure)
        if row.get("gaze"):
            st.gaze = row["gaze"]
        st.transition_style = row.get("transition", st.transition_style)
        reasons.append(f"mode_{mode}")

    # ------------------------------------------------------------------ persona 调制（真正把人分开）
    def _apply_persona(self, st: BodyExpressionState, mode: str, reasons: List[str]) -> None:
        p = self.persona
        # 1. 表演性放大系数：演出/自傲模式上幅度明显；普通模式影响更小（避免"乱动"）
        st.movement_amplitude = self._clamp(
            st.movement_amplitude * (0.7 + p.theatrical_modulation * 0.6))
        # 2. 开放度基线：Neutral 更开放；Mask 收着。向 persona 基线靠拢（不覆盖 activity 之后的结果）
        st.body_openness = self._clamp(
            st.body_openness * 0.6 + p.openness_baseline * 0.4)
        # 3. 骄傲挺直：PROUD/PERFORMATIVE 且 pride 高 → 挺直 + 克制上升；pride 低(Neutral)不太挺
        if mode in (PersonaMode.PROUD.value, PersonaMode.PERFORMATIVE.value):
            if p.posture_pride > 0.6:
                st.posture = PostureIntent.UPRIGHT.value
                st.composure = self._clamp(st.composure + p.posture_pride * 0.15)
            elif p.posture_pride < 0.4:
                st.posture = PostureIntent.RELAXED.value
                st.composure = self._clamp(st.composure - 0.05)
        # 4. 视线自然度：naturalness 高(Furina) → 默认在场但不死盯，给自然切换空间；
        #    low(Mask) → 习惯被注视，倾向 USER / 少切。
        if p.gaze_naturalness < 0.4 and st.gaze in (GazeIntent.AROUND.value, GazeIntent.NONE.value):
            st.gaze = GazeIntent.USER.value
        # 5. guarded→sincere 过渡：sincere 意愿高(Furina) 真诚时不端着；低(Mask) 仍维持克制
        if mode == PersonaMode.SINCERE.value:
            st.movement_amplitude = self._clamp(
                st.movement_amplitude * (0.6 + p.guarded_to_sincere * 0.5))
            if p.guarded_to_sincere > 0.6:
                st.composure = self._clamp(st.composure - 0.1)
                st.body_openness = self._clamp(st.body_openness + 0.1)
        # 6. 脆弱可见度：vulnerability 高(Furina/Neutral) 情绪低落时可见；低(Mask) 藏着
        if mode in (PersonaMode.VULNERABLE.value,) and p.vulnerability_visibility < 0.4:
            st.composure = self._clamp(st.composure + 0.25)
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.2))
        # 7. 常驻"端着"：Mask 永不彻底放松（composure 抬高、开放压低）
        if p.always_presents:
            st.composure = self._clamp(max(st.composure, 0.8))
            st.body_openness = self._clamp(min(st.body_openness, 0.5))
        # 8. 社交迟疑基线（§12）：被关注/在场时的本能迟疑。persona 的 recognition_hesitation 决定。
        #    Furina 高(有曲折)，Neutral 低(直白)，Mask 低但用"克制"替代迟疑(composure 已高)。
        st.hesitation = self._clamp(st.hesitation + (p.recognition_hesitation - 0.5) * 0.3)
        reasons.append(f"embodiment_{p.key}")

    # ------------------------------------------------------------------ emotion 非脸维度
    def _apply_emotion_body(self, st: BodyExpressionState, emotion: str, reasons: List[str]) -> None:
        arousal = {
            "excited": (TempoIntent.ENERGETIC.value, 0.8), "proud": (TempoIntent.LIVELY.value, 0.65),
            "happy": (TempoIntent.LIVELY.value, 0.6), "curious": (TempoIntent.NORMAL.value, 0.5),
            "calm": (TempoIntent.SLOW.value, 0.4), "sleepy": (TempoIntent.VERY_SLOW.value, 0.2),
            "embarrassed": (TempoIntent.NORMAL.value, 0.35), "annoyed": (TempoIntent.NORMAL.value, 0.3),
            "sad": (TempoIntent.SLOW.value, 0.25), "lonely": (TempoIntent.SLOW.value, 0.25),
        }
        tempo, amp_scale = arousal.get(emotion, (TempoIntent.NORMAL.value, 0.5))
        # tempo 由情绪唤醒度调制，但不下压 mode 已定的 tempo（只在更"安静"时生效）
        if st.movement_tempo in (TempoIntent.NORMAL.value, TempoIntent.LIVELY.value, TempoIntent.ENERGETIC.value):
            st.movement_tempo = tempo if tempo in (TempoIntent.VERY_SLOW.value, TempoIntent.SLOW.value) else st.movement_tempo
        st.movement_amplitude = self._clamp(st.movement_amplitude * (0.5 + amp_scale * 0.6))
        # hesitation：embarrassed/sad 升高；gaze 由情绪调制
        if emotion in ("embarrassed", "sad", "lonely"):
            st.hesitation = self._clamp(st.hesitation + 0.25)
        if emotion == "lonely":
            st.gaze = GazeIntent.AROUND.value
        elif emotion == "embarrassed":
            # 被夸/尴尬：**先短暂避开视线再回**（§1/§18）。SINCERE/高信任的关系调制会在
            # 之后回正到 USER；否则保持侧视（低信任习惯性回避）。
            if st.gaze not in (GazeIntent.USER.value, GazeIntent.SIDE.value):
                st.gaze = GazeIntent.SIDE.value
        reasons.append(f"emotion_body_{emotion}")

    # ------------------------------------------------------------------ relationship
    def _apply_relationship(self, st: BodyExpressionState, rel: Dict, apt: CharacterAppraisal,
                            recent_rejection: bool, reasons: List[str]) -> None:
        trust = float(rel.get("trust", 0.5))
        fam = float(rel.get("familiarity", 0.5))
        comfort = float(rel.get("comfort", 0.5))
        annoyance = float(rel.get("annoyance", 0.1))
        openness_bonus = 0.0
        if trust > 0.6:
            openness_bonus += 0.15
        if fam < 0.3:
            st.composure = self._clamp(st.composure + 0.15)
            st.body_openness = self._clamp(st.body_openness - 0.15)
            st.gaze = GazeIntent.SIDE.value if st.gaze in (GazeIntent.USER.value, GazeIntent.NONE.value) else st.gaze
            reasons.append("low_familiarity_guarded")
        elif comfort > 0.6:
            openness_bonus += 0.1
            reasons.append("high_comfort_open")
        st.body_openness = self._clamp(st.body_openness + openness_bonus)
        if annoyance > 0.6:
            st.body_openness = self._clamp(st.body_openness - 0.25)
            st.gaze = GazeIntent.SIDE.value   # 少对视（§22 不是 angry face）
            st.movement_tempo = TempoIntent.NORMAL.value
            st.micro_motion = [MicroMotionIntent.NONE.value]
            reasons.append("annoyance_close")
        # 被拒 → 收敛靠近意愿（§20）；这里只影响 openness/hesitation，proximity 在 contradiction 处理
        if recent_rejection:
            st.hesitation = self._clamp(st.hesitation + 0.3)
            reasons.append("recent_rejection")
        # CharacterAppraisal：被关注/被认可 → 迟疑与姿态（recognition）
        if apt.recognition_opportunity > 0.4:
            st.hesitation = self._clamp(st.hesitation + (self.persona.recognition_hesitation - 0.5) * 0.4)
            if st.posture not in (PostureIntent.RELAXED.value, PostureIntent.LYING.value):
                st.posture = PostureIntent.UPRIGHT.value
            reasons.append("recognition_opportunity")

    # ------------------------------------------------------------------ fatigue 覆盖
    def _apply_fatigue(self, st: BodyExpressionState, fatigue: float, reasons: List[str]) -> None:
        if fatigue >= 70:
            st.movement_tempo = TempoIntent.VERY_SLOW.value
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.25))
            if st.posture in (PostureIntent.UPRIGHT.value, PostureIntent.ENGAGED.value):
                st.posture = PostureIntent.RELAXED.value
            st.composure = self._clamp(st.composure - 0.2)   # 很累难撑住体面
            st.micro_motion = [MicroMotionIntent.SIGH.value, MicroMotionIntent.YAWN.value]
            reasons.append("fatigue_override")
        elif fatigue >= 45:
            st.movement_tempo = TempoIntent.SLOW.value
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.5))
            reasons.append("fatigue_moderate")

    # ------------------------------------------------------------------ speech / silence
    def _apply_speech(self, st: BodyExpressionState, dialogue_act: str,
                      speech_intent: Optional[SpeechIntent], silence: bool, reasons: List[str]) -> None:
        if silence:
            # 沉默时身体仍要表达（§27）：由 emotion/mode/activity 天然决定，这里只确保不"冻结"
            st.speech_sync = SpeechSync.NONE.value
            reasons.append("silence_body_alive")
            return
        if speech_intent is not None:
            di = float(speech_intent.dramatic_intensity or 0.5)
            if di > 0.6:
                st.movement_amplitude = self._clamp(st.movement_amplitude + 0.15)
                reasons.append("speech_animated")
        # DialogueAct 协调（§26）：BOAST→挺直上升，SINCERE→装饰下降，OFFER_HELP→专注稳定
        if dialogue_act == DialogueAct.BOAST.value:
            st.posture = PostureIntent.UPRIGHT.value
            st.composure = self._clamp(st.composure + 0.1)
            reasons.append("act_boast")
        elif dialogue_act == DialogueAct.OFFER_HELP.value:
            st.gaze = GazeIntent.USER.value
            st.posture = PostureIntent.ENGAGED.value
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.4))
            reasons.append("act_offer_help")
        elif dialogue_act == DialogueAct.ADMIT.value:
            st.gaze = GazeIntent.DOWN.value
            st.composure = self._clamp(st.composure - 0.1)
            reasons.append("act_admit")

    # ------------------------------------------------------------------ activity 兼容
    def _apply_activity(self, st: BodyExpressionState, activity: str, user_working: bool,
                        reasons: List[str]) -> None:
        act = activity or "idle"
        if act == "sleep":
            st.posture = PostureIntent.SLEEPING.value
            st.gaze = GazeIntent.NONE.value           # §29 sleeping→gaze_user invalid
            st.movement_tempo = TempoIntent.VERY_SLOW.value
            st.movement_amplitude = 0.05
            st.micro_motion = [MicroMotionIntent.BREATH.value]
            reasons.append("activity_sleep")
        elif act in ("rest", "nap"):
            st.posture = PostureIntent.LYING.value if act == "rest" else PostureIntent.SLEEPING.value
            st.movement_tempo = TempoIntent.SLOW.value
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.2))
            reasons.append(f"activity_{act}")
        elif act in ("read", "think", "daydream"):
            st.posture = PostureIntent.SEATED.value
            st.gaze = GazeIntent.SCREEN.value if act in ("read", "think") else GazeIntent.AROUND.value
            st.movement_tempo = TempoIntent.SLOW.value
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.3))
            reasons.append(f"activity_{act}_screen")
        elif act in ("eat", "drink"):
            st.posture = PostureIntent.SEATED.value
            st.movement_amplitude = self._clamp(min(st.movement_amplitude, 0.3))   # §29 无关大动作抑制
            reasons.append(f"activity_{act}")
        elif act in ("observe_user", "approach_user", "watch_user", "offer_help"):
            st.gaze = GazeIntent.USER.value
            reasons.append(f"activity_{act}_user")
        elif act in ("observe_work", "assist_user"):
            st.gaze = GazeIntent.SCREEN.value
            reasons.append(f"activity_{act}_screen")
        elif user_working:
            st.gaze = GazeIntent.SCREEN.value
            reasons.append("user_working_screen")
        # 深层"工作/专注"下自然生命：确保有呼吸/眨眼类 micro
        if st.micro_motion and MicroMotionIntent.BREATH.value not in st.micro_motion:
            if act in ("sleep", "rest", "read", "think"):
                st.micro_motion = [MicroMotionIntent.BREATH.value] + st.micro_motion

    # ------------------------------------------------------------------ 矛盾/迟疑
    def _apply_contradiction(self, st: BodyExpressionState, apt: CharacterAppraisal,
                             social_motive: float, recent_rejection: bool, rel: Dict,
                             reasons: List[str]) -> None:
        # 想靠近 + 可能被拒 + 高社交 → 想靠近但迟疑（§20）。不强关 approach，只表达冲突。
        want_near = social_motive > 0.5 and float(rel.get("trust", 0)) > 0.3
        if want_near and (recent_rejection or apt.dignity_threat > 0.4):
            st.proximity = ProximityIntent.APPROACH.value
            # persona 迟疑倾向：Furina 对被关注/接近有更多"曲折"（recognition_hesitation 高），
            # Neutral 更直白，Mask 习惯被注视几乎不迟疑。
            hes = self.persona.recognition_hesitation
            st.hesitation = self._clamp(st.hesitation + 0.2 + hes * 0.25)
            st.gaze = GazeIntent.USER.value if hes < 0.4 else GazeIntent.SIDE.value
            st.movement_amplitude = self._clamp(st.movement_amplitude - 0.1)
            st.transition_style = TransitionStyle.HESITANT.value
            reasons.append("approach_hesitation")

    # ------------------------------------------------------------------ micro preference
    def _micro_preference(self, st: BodyExpressionState, fatigue: float, reasons: List[str]) -> List[str]:
        prefs: List[str] = []
        base = [MicroMotionIntent.BLINK.value]
        # 呼吸作为基础生命循环 always available（不由本层关闭）
        base.append(MicroMotionIntent.BREATH.value)
        # 疲劳 → 哈欠/伸展机会上升
        if fatigue >= 50:
            prefs.append(MicroMotionIntent.YAWN.value)
            prefs.append(MicroMotionIntent.STRETCH.value)
        # playful → giggle 机会上升
        if st.movement_tempo in (TempoIntent.LIVELY.value, TempoIntent.ENERGETIC.value):
            prefs.append(MicroMotionIntent.GIGGLE.value)
        # guarded → 装饰性 micro 减少
        if st.composure > 0.8 and st.body_openness < 0.4:
            prefs = [m for m in prefs if m != MicroMotionIntent.GIGGLE.value]
        # 尴尬/迟疑 → 视线/小动作
        if st.hesitation > 0.6:
            prefs.append(MicroMotionIntent.LOOK_SHIFT.value)
            prefs.append(MicroMotionIntent.FIDGET.value)
        unique = list(dict.fromkeys(base + prefs))
        return unique[:5]

    # ------------------------------------------------------------------ transition
    def _transition(self, emotion: str, mode: str, st: BodyExpressionState, reasons: List[str]) -> str:
        if st.hesitation > 0.65:
            return TransitionStyle.HESITANT.value
        if emotion == "embarrassed":
            return TransitionStyle.HESITANT.value
        if st.movement_tempo in (TempoIntent.ENERGETIC.value, TempoIntent.LIVELY.value):
            return TransitionStyle.ENERGETIC.value
        if mode == PersonaMode.SINCERE.value or st.body_openness > 0.7:
            return TransitionStyle.GENTLE.value
        if st.composure > 0.8:
            return TransitionStyle.IMMEDIATE.value
        return TransitionStyle.SMOOTH.value

    @staticmethod
    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @staticmethod
    def signature(st: BodyExpressionState) -> tuple:
        """去身份/去情绪的**纯身体**指纹（供 Hard-Blind）。"""
        return (st.expression, st.gaze, st.posture,
                round(st.body_openness, 2), st.proximity, st.movement_tempo,
                round(st.movement_amplitude, 2), round(st.hesitation, 2),
                round(st.composure, 2), tuple(sorted(st.micro_motion)), st.transition_style)
