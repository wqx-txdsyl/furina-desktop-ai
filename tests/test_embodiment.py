"""Phase 09: Embodied Expression / Body Language 测试（§45）。"""
from __future__ import annotations

from furina.embodiment import (
    EmbodiedExpressionEngine, BodyValidator, BodyExpressionState,
    FURINA_EMBODIMENT, NEUTRAL_EMBODIMENT, FORMER_MASK_EMBODIMENT,
    GazeIntent, PostureIntent, TempoIntent, SpeechSync,
)
from furina.dialogue import SpeechIntent, PersonaMode, DialogueAct
from furina.persona.character_identity import CharacterAppraisal

_eng_f = EmbodiedExpressionEngine(FURINA_EMBODIMENT)
_eng_n = EmbodiedExpressionEngine(NEUTRAL_EMBODIMENT)
_eng_m = EmbodiedExpressionEngine(FORMER_MASK_EMBODIMENT)
_val = BodyValidator()


def _rel(**kw):
    d = {"trust": 0.5, "comfort": 0.5, "annoyance": 0.1, "familiarity": 0.5}
    d.update(kw)
    return d


def _expr(eng=_eng_f, **kw):
    defaults = dict(emotion="calm", mode=PersonaMode.CASUAL.value,
                    dialogue_act=DialogueAct.COMMENT.value, relationship=_rel(),
                    activity="idle", fatigue=20.0, silence=False)
    defaults.update(kw)
    return eng.express(**defaults)


# ---------------------------------------------------------------- emotion_changes_body
def test_emotion_changes_body():
    """Emotion 不只改脸：同 mode/relationship 下，proud vs embarrassed vs sad 身体维度不同。"""
    p = _expr(emotion="proud", mode=PersonaMode.PROUD.value)
    e = _expr(emotion="embarrassed", mode=PersonaMode.PROUD.value)
    s = _expr(emotion="sad", mode=PersonaMode.PROUD.value)
    assert p.expression != e.expression != s.expression
    # 各自 body signature 两两不同（至少在某身体维度分化，而非只换表情）
    assert EmbodiedExpressionEngine.signature(p) != EmbodiedExpressionEngine.signature(e)
    assert EmbodiedExpressionEngine.signature(e) != EmbodiedExpressionEngine.signature(s)
    assert EmbodiedExpressionEngine.signature(p) != EmbodiedExpressionEngine.signature(s)
    # 三个都该"高唤醒"模样的 proud 与"低能量"的 sad 在 tempo/振幅分化
    assert p.movement_tempo != s.movement_tempo or p.movement_amplitude > s.movement_amplitude


# ---------------------------------------------------------------- persona_mode_changes_body
def test_persona_mode_changes_body():
    """PersonaMode 直接改身体：PERFORMATIVE vs GUARDED vs SINCERE 差异明显。"""
    perf = _expr(mode=PersonaMode.PERFORMATIVE.value)
    guard = _expr(mode=PersonaMode.GUARDED.value)
    sinc = _expr(mode=PersonaMode.SINCERE.value)
    assert perf.posture == PostureIntent.UPRIGHT.value
    assert guard.posture == PostureIntent.CONTAINED.value
    assert guard.body_openness < perf.body_openness
    assert sinc.composure < perf.composure        # sincere 更不设防
    assert perf.movement_amplitude > sinc.movement_amplitude  # 表演幅度大


# ---------------------------------------------------------------- relationship_changes_body
def test_relationship_changes_body():
    """关系真正改变身体距离与开放度：high trust vs low familiarity vs annoyance。"""
    hi = _expr(relationship=_rel(trust=0.9, familiarity=0.9, comfort=0.9))
    lo = _expr(relationship=_rel(trust=0.2, familiarity=0.15, comfort=0.2))
    ann = _expr(relationship=_rel(trust=0.5, familiarity=0.5, annoyance=0.9))
    assert hi.body_openness > lo.body_openness
    assert lo.composure > hi.composure
    assert ann.gaze == GazeIntent.SIDE.value
    assert ann.body_openness < hi.body_openness


# ---------------------------------------------------------------- praise_embarrassed_gaze
def test_praise_embarrassed_gaze():
    """被夸（embarrassed）→ 视线不永久盯用户：hesitation↑、可能 SIDE/LOOK_SHIFT。"""
    e = _expr(emotion="embarrassed", mode=PersonaMode.PROUD.value,
              appraisal=CharacterAppraisal(recognition_opportunity=0.8))
    assert e.hesitation > 0.5
    assert e.transition_style in ("HESITANT",)
    assert e.micro_motion and ("LOOK_SHIFT" in e.micro_motion or "FIDGET" in e.micro_motion)


def test_praise_proud_gaze_user():
    """被夸（proud）→ 姿态挺直、视线朝用户、克制高。"""
    p = _expr(emotion="proud", mode=PersonaMode.PROUD.value,
              appraisal=CharacterAppraisal(recognition_opportunity=0.8))
    assert p.posture == PostureIntent.UPRIGHT.value
    assert p.composure >= 0.7


# ---------------------------------------------------------------- failure_x_relationship_body
def test_failure_x_relationship_body():
    """同一个失败：低熟悉 → 克制/防御/少对视；高信任 → 更低克制/更真诚。"""
    lo = _expr(emotion="embarrassed", mode=PersonaMode.GUARDED.value,
               relationship=_rel(trust=0.2, familiarity=0.2))
    hi = _expr(emotion="embarrassed", mode=PersonaMode.SINCERE.value,
               relationship=_rel(trust=0.9, familiarity=0.9, comfort=0.9))
    assert lo.composure >= hi.composure
    assert lo.body_openness <= hi.body_openness
    assert lo.gaze != GazeIntent.USER.value   # 低熟悉少对视


# ---------------------------------------------------------------- genuine_care_body
def test_genuine_care_body():
    """genuine care（help+high trust+RESPONSIBLE/SINCERE）→ 装饰↓ 视线稳 开放↑ 犹豫↓。"""
    care = _expr(emotion="calm", mode=PersonaMode.RESPONSIBLE.value,
                 dialogue_act=DialogueAct.OFFER_HELP.value,
                 relationship=_rel(trust=0.9, comfort=0.9), activity="offer_help")
    assert care.gaze == GazeIntent.USER.value
    assert care.movement_amplitude <= 0.5     # 幅度受控
    assert care.movement_tempo in (TempoIntent.NORMAL.value, TempoIntent.SLOW.value)
    assert care.body_openness >= 0.5


# ---------------------------------------------------------------- contradiction_hesitation
def test_contradiction_hesitation():
    """想靠近 + 被拒 + 高社交 → 想靠近但迟疑，不强行取消。"""
    c = _expr(emotion="calm", mode=PersonaMode.CASUAL.value,
              relationship=_rel(trust=0.4), social_motive=0.8, recent_rejection=True,
              appraisal=CharacterAppraisal(dignity_threat=0.5))
    assert c.proximity in ("APPROACH", "MAINTAIN")
    assert c.hesitation > 0.5
    assert c.transition_style == "HESITANT"


# ---------------------------------------------------------------- fatigue_overrides_energy
def test_fatigue_overrides_energy():
    """proud + 极高疲劳 → 不能被"有气场"顶起来：tempo 慢、振幅小、不挺直。"""
    p = _expr(emotion="proud", mode=PersonaMode.PERFORMATIVE.value, fatigue=95.0)
    assert p.movement_tempo in (TempoIntent.VERY_SLOW.value, TempoIntent.SLOW.value)
    assert p.movement_amplitude <= 0.3
    assert p.posture != PostureIntent.UPRIGHT.value
    # 对照：同 input 但低疲劳 → 表演姿可挺直
    p_lo = _expr(emotion="proud", mode=PersonaMode.PERFORMATIVE.value, fatigue=10.0)
    assert p_lo.posture == PostureIntent.UPRIGHT.value


# ---------------------------------------------------------------- activity_pose_compatibility
def test_activity_pose_compatibility():
    """Activity 是最高约束：sleep→睡觉姿（不能 upright），read→坐。"""
    s = _val.validate(_expr(emotion="proud", mode=PersonaMode.PERFORMATIVE.value,
                            activity="sleep", fatigue=10.0), activity="sleep")
    assert s.posture == PostureIntent.SLEEPING.value
    assert s.gaze == GazeIntent.NONE.value
    r = _val.validate(_expr(emotion="excited", mode=PersonaMode.PLAYFUL.value, activity="read"),
                      activity="read")
    assert r.posture == PostureIntent.SEATED.value


# ---------------------------------------------------------------- silence_still_has_body
def test_silence_still_has_body():
    """speech=None（should_speak=False）→ 身体仍表达：非 frozen，有 micro/breath。"""
    sil = _expr(emotion="calm", mode=PersonaMode.CASUAL.value, silence=True,
                activity="read")
    assert sil.speech_sync == SpeechSync.NONE.value
    assert sil.micro_motion and "BREATH" in sil.micro_motion
    assert sil.posture in (PostureIntent.SEATED.value, PostureIntent.RELAXED.value)


# ---------------------------------------------------------------- quiet_coexistence
def test_quiet_coexistence():
    """用户工作 + 她自活 + 无 speech → 不为了存在感不停看用户。"""
    q = _expr(emotion="calm", mode=PersonaMode.CASUAL.value, activity="read",
              user_working=True, silence=True, user_present=True)
    assert q.gaze != GazeIntent.USER.value or q.movement_amplitude < 0.4
    # 不崩溃成"每 5 秒 sigh"
    assert q.micro_motion.count("SIGH") <= 1


# ---------------------------------------------------------------- micro_motion_cooldown(通过偏好多样性)
def test_micro_motion_no_sigh_dominance():
    """sad 不塌缩成高 sigh：micro 是**偏好**列表，不因情绪只剩 sigh。"""
    s = _expr(emotion="sad", mode=PersonaMode.VULNERABLE.value, fatigue=40.0)
    assert s.micro_motion.count("SIGH") <= 1
    assert len(s.micro_motion) >= 2


# ---------------------------------------------------------------- body_dialogue_consistency
def test_body_dialogue_consistency():
    """SINCERE/ADMIT 不能表演幅度拉满/挺直；BOAST 不能脆弱拉满/视线持续向下。"""
    sinc = _expr(mode=PersonaMode.SINCERE.value, dialogue_act=DialogueAct.ADMIT.value,
                 emotion="embarrassed")
    assert sinc.movement_amplitude <= 0.5
    assert sinc.gaze != GazeIntent.SIDE.value or sinc.expression != "proud"  # 真诚时不端着
    boast = _expr(mode=PersonaMode.PROUD.value, dialogue_act=DialogueAct.BOAST.value, emotion="proud")
    assert boast.composure >= 0.7
    assert boast.posture == PostureIntent.UPRIGHT.value
    assert boast.gaze != GazeIntent.DOWN.value


# ---------------------------------------------------------------- current_vs_neutral_body
def test_current_vs_neutral_body():
    """Current Furina vs Neutral：稳定、非夸张的 body signature 差异。"""
    # 同输入，仅 embodiment persona 不同
    f = _expr(_eng_f, emotion="happy", mode=PersonaMode.CASUAL.value)
    n = _expr(_eng_n, emotion="happy", mode=PersonaMode.CASUAL.value)
    assert EmbodiedExpressionEngine.signature(f) != EmbodiedExpressionEngine.signature(n)
    # Furina 戏剧/表现更强；Neutral 更随意开放
    assert f.movement_amplitude > n.movement_amplitude
    assert n.body_openness >= f.body_openness


# ---------------------------------------------------------------- current_vs_mask_body
def test_current_vs_mask_body():
    """Current vs Former Mask：Mask 更克制/挺直/表演幅度更高/开放更低。"""
    f = _expr(_eng_f, emotion="proud", mode=PersonaMode.PERFORMATIVE.value)
    m = _expr(_eng_m, emotion="proud", mode=PersonaMode.PERFORMATIVE.value)
    assert m.composure >= f.composure
    assert m.body_openness <= f.body_openness
    assert m.movement_amplitude >= f.movement_amplitude
    assert m.posture == f.posture    # 同为挺直（表演）


def test_current_can_relax_mask_cannot():
    """普通 casual：Current 能放松/真诚；Mask 保持端着（composure/挺直）。"""
    f = _expr(_eng_f, emotion="calm", mode=PersonaMode.CASUAL.value)
    m = _expr(_eng_m, emotion="calm", mode=PersonaMode.CASUAL.value)
    assert f.body_openness > m.body_openness
    assert f.movement_amplitude >= m.movement_amplitude or f.gaze == "AROUND"


# ---------------------------------------------------------------- body_collapse
def test_body_collapse_user_gaze_not_dominant():
    """普通生活不塌缩成永远盯用户：多数场景 gaze≠USER。"""
    sts = [_expr(emotion=e, mode=m, activity=a)
           for e in ("calm", "happy", "sad", "sleepy")
           for m in (PersonaMode.CASUAL.value, PersonaMode.SINCERE.value)
           for a in ("read", "idle", "rest", "think")]
    user_gaze = sum(1 for s in sts if s.gaze == GazeIntent.USER.value)
    assert user_gaze / len(sts) < 0.6, f"user-gaze 占比 {user_gaze/len(sts):.2f} >= 60%"
    upright = sum(1 for s in sts if s.posture == PostureIntent.UPRIGHT.value)
    assert upright / len(sts) < 0.6
