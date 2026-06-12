"""
model.py — NeuroScan scoring engine v5
Key fix: emotional_valence now modulates face_score before stress calculation.
Happy/laughing face correctly reduces stress output.
"""
from typing import List


LOW_MAX, MED_MAX = 30, 60


def _apply_valence_correction(face: float, valence: str, emotion: str) -> float:
    """
    Correct face_score based on emotional valence.
    A happy/laughing person's physiological stress should be low
    even if raw face detection was uncertain.
    """
    POSITIVE = {"happy", "laughing", "amused", "joyful", "content", "smiling", "excited"}
    NEGATIVE  = {"angry", "fearful", "fear", "disgusted", "disgust", "distressed"}

    em = emotion.lower()
    if valence == "positive" or em in POSITIVE:
        # Positive emotion: cap face stress at 25 unless extreme tension
        return min(face, 25)
    elif valence == "negative" or em in NEGATIVE:
        # Negative emotion: boost face score slightly (floor at 45)
        return max(face, 45)
    # neutral — no correction
    return face


def _level(s: float) -> str:
    return "Low 😊" if s < LOW_MAX else ("Moderate 😐" if s < MED_MAX else "High ⚠️")


def _risk(s: float) -> str:
    return "No Risk ✅" if s < LOW_MAX else ("Mild Risk ⚠️" if s < MED_MAX else "High Anxiety Risk 🚨")


def _focus_score(face: float, blink: float, voice: float) -> float:
    blink_f = max(0, 100 - blink * 1.2)
    face_f  = max(0, 100 - face)
    voice_f = max(0, 100 - voice * 0.8)
    return round(min(100, blink_f * 0.4 + face_f * 0.35 + voice_f * 0.25), 1)


def _fatigue_score(blink: float, face: float) -> float:
    blink_f = max(0, 60 - abs(blink - 15) * 2)
    face_f  = face * 0.5
    return round(min(100, blink_f * 0.6 + face_f * 0.4), 1)


def _anxiety_score(voice: float, face: float, stress: float) -> float:
    return round(min(100, voice * 0.45 + face * 0.35 + stress * 0.2), 1)


def _hrv_estimate(stress: float) -> float:
    return round(max(20, 65 - stress * 0.4), 1)


def _heart_rate_estimate(stress: float, blink: float) -> int:
    return round(min(120, max(55, 72 + stress * 0.35 + blink * 0.08)))


def _suggestions(s: float, emotion: str = "neutral") -> List[str]:
    em = emotion.lower()
    if em in {"happy", "laughing", "amused", "joyful"}:
        return [
            "Great mood detected! Harness this positive energy 🌟",
            "Perfect time for creative tasks or team collaboration",
            "Your stress levels are low — ideal for challenging work"
        ]
    if s < LOW_MAX:
        return [
            "You're calm — great state for deep work 🙌",
            "Maintain this balance with micro-breaks every 90 min",
            "Ideal time for creative or complex tasks"
        ]
    elif s < MED_MAX:
        return [
            "Take a 5-minute break every hour",
            "Stay hydrated — drink water 💧",
            "Try box breathing: inhale 4s, hold 4s, exhale 4s",
            "Stretch your neck and shoulders gently"
        ]
    else:
        return [
            "Practice deep diaphragmatic breathing 🧘",
            "Step away from the screen for 10 minutes",
            "Listen to calm / ambient music 🎵",
            "Consider a short walk outside 🌿",
            "Talk to someone you trust about your workload",
            "Avoid caffeine for the next few hours"
        ]


def _reasons(face: float, blink: float, voice: float,
             stress_indicators: list = None, emotion: str = "neutral") -> List[str]:
    items = []
    em = emotion.lower()
    POSITIVE = {"happy", "laughing", "amused", "joyful", "content", "smiling"}

    if em in POSITIVE:
        items.append(f"Positive emotion ({emotion}) detected — stress naturally suppressed")
        return items

    # Use Claude's detected stress indicators if available
    if stress_indicators:
        for ind in stress_indicators[:3]:  # max 3
            items.append(ind)

    if not stress_indicators:
        if face >= 65:   items.append("High facial muscle tension detected")
        elif face >= 45: items.append("Mild facial tension observed")
        if voice >= 65:  items.append("Elevated voice stress patterns")
        elif voice >= 45: items.append("Slight increase in voice pitch variability")
        if blink >= 65:  items.append("Rapid eye-blink rate — possible anxiety")
        elif blink >= 45: items.append("Above-average blink frequency noted")
        if blink < 10 and blink > 0: items.append("Very low blink rate — intense focus or eye strain")

    if not items:
        items.append("All biometric signals within normal range")
    return items


def calculate_stress(
    face: float, blink: float, voice: float,
    valence: str = "neutral", emotion: str = "neutral",
    stress_indicators: list = None
) -> dict:
    # Apply emotion/valence correction to face score FIRST
    corrected_face = _apply_valence_correction(face, valence, emotion)

    stress = round(corrected_face * 0.35 + blink * 0.30 + voice * 0.35, 2)
    stress = max(0.0, min(100.0, stress))

    # Hard cap: positive emotional state cannot produce high stress reading
    em_lower = emotion.lower()
    POSITIVE_EMOTIONS = {"happy", "laughing", "amused", "joyful", "content", "smiling", "excited"}
    if valence == "positive" or em_lower in POSITIVE_EMOTIONS:
        stress = min(stress, 38.0)  # never report >38% stress when laughing/happy

    avg      = (corrected_face + blink + voice) / 3
    variance = sum((x - avg) ** 2 for x in [corrected_face, blink, voice]) / 3
    confidence = round(max(60, 92 - variance * 0.15), 1)

    focus   = _focus_score(corrected_face, blink, voice)
    fatigue = _fatigue_score(blink, corrected_face)
    anxiety = _anxiety_score(voice, corrected_face, stress)
    hrv     = _hrv_estimate(stress)
    hr      = _heart_rate_estimate(stress, blink)

    return {
        "stress":            stress,
        "focus":             focus,
        "fatigue":           fatigue,
        "anxiety":           anxiety,
        "hrv":               hrv,
        "heart_rate":        hr,
        "binary":            1 if stress > 50 else 0,
        "level":             _level(stress),
        "risk":              _risk(stress),
        "reasons":           _reasons(corrected_face, blink, voice, stress_indicators, emotion),
        "suggestions":       _suggestions(stress, emotion),
        "accuracy":          f"{confidence}%",
        "corrected_face":    round(corrected_face, 1),
        "components": {
            "face":  round(corrected_face, 1),
            "blink": round(blink, 1),
            "voice": round(voice, 1)
        }
    }


# ── Baseline-relative helper (added) ──────────────────────────────────────
def relative_to_baseline(stress: float, baseline: float) -> dict:
    """
    Compare current stress to user's personal baseline.
    Returns delta and a human-readable label.
    """
    if not baseline or baseline <= 0:
        return {"delta": 0, "label": "No baseline set", "direction": "neutral"}

    delta = round(stress - baseline, 1)
    if delta > 10:
        label = f"{abs(delta)}% above your normal"
        direction = "up"
    elif delta < -10:
        label = f"{abs(delta)}% below your normal"
        direction = "down"
    else:
        label = "Near your normal baseline"
        direction = "neutral"

    return {"delta": delta, "label": label, "direction": direction}
