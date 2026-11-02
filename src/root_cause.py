"""Root-cause analysis + personalised, actionable guidance.

How it works (plain words)
--------------------------
1. The ML model gives ONE number: the predicted Mental Health Score (0-10, higher = healthier).
2. One number cannot say *why*. So every habit is also scored on its own for how far it sits from a healthy
   target (its SEVERITY: 0 = fine ... 1 = far from target). This uses the person's REAL values.
3. Each habit has a WEIGHT (how much it matters). impact = weight x severity. Two students who get the same
   final score but have different habits therefore get different root causes and different plans.
4. Habits are ranked by impact -> root causes -> a plan whose steps are built from the person's own numbers.
5. The SCORE also shapes the guidance: it decides the mode (support / balance / maintain) and the tone.
6. For each root cause we ask the trained model a what-if: "if only this habit reached its target, how would the
   predicted score change?" It is shown only when the model sees a real change, and is never a promise.

Weights: screen time and sleep carry the most weight because they are the strongest signals in the trained model
(permutation importance). Stress is the *signal* (how the person feels), habits are the *causes*. Workload and
activity keep solid weights on general lifestyle-guidance grounds; in this dataset they have little independent
effect on the score, which is why the model what-if can be ~0 for them.

This is lifestyle guidance, not clinical advice, and it does not claim that a habit *caused* a mental-health outcome.
"""
from __future__ import annotations
import math
from . import prescription as _prescription

GUIDANCE_VERSION = "2.0"

DISCLAIMER = ("MindPulse offers lifestyle and activity guidance based on a statistical model of a student survey "
              "dataset. It is not medical or clinical advice and cannot diagnose any condition. If you are worried "
              "about your health or mood, please speak with a qualified professional.")

SUPPORT_NOTE = ("If you have felt overwhelmed for more than a couple of weeks, or it is getting in the way of daily "
                "life, please talk to someone you trust, a campus counsellor, or a doctor. Reaching out early is a "
                "strength, not a failure.")

# key -> (label, weight, kind). Weights sum to 100.
FACTORS = {
    "sleep":          ("Sleep", 24, "habit"),
    "screen_time":    ("Screen time", 22, "habit"),
    "stress":         ("Perceived stress", 18, "signal"),
    "activity":       ("Physical activity", 14, "habit"),
    "workload":       ("Study workload", 12, "habit"),
    "phone_checking": ("Phone checking", 10, "habit"),
}
TOTAL_WEIGHT = sum(w for _, w, _ in FACTORS.values())
HABIT_KEYS = [k for k, (_, _, kind) in FACTORS.items() if kind == "habit"]
REPORT_THRESHOLD = 0.25     # severity needed before a habit is reported as a root cause
WATCH_THRESHOLD = 0.08      # below REPORT but above this -> "keep an eye on it"
STRESS_SEVERITY = {"Low": 0.0, "Medium": 0.30, "High": 0.65, "Very High": 1.0}

# Overall mode thresholds (score = model output, pressure = weighted habit pressure 0-100)
SUPPORT_SCORE, HEALTHY_SCORE = 5.5, 7.0
SUPPORT_PRESSURE, HEALTHY_PRESSURE = 40, 22
SEVERE_HABIT = 0.75          # one habit this far from target is enough for "support", even if the average looks fine


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def severities(d: dict) -> dict:
    """0 (on target) .. 1 (far from target) for every factor. Uses the person's real (unclipped) values."""
    sleep, study = d["sleep_hours_per_night"], d["study_hours"]
    oversleep = _clip((sleep - 9.5) / 2.5, 0, 0.5)               # far above 9 h: only a mild flag
    workload = _clip((study - 5) / 3)
    if study >= 4 and sleep < 6.5:                                # study is eating into sleep
        workload = _clip(workload + 0.15)
    return {
        "sleep": _clip((7 - sleep) / 3) if sleep < 7 else oversleep,
        "screen_time": _clip((d["avg_daily_usage_hours"] - 4) / 4),
        "stress": STRESS_SEVERITY[d["stress_level"]],
        "activity": _clip(1.0 - d["physical_activity_hours"]),
        "workload": workload,
        "phone_checking": _clip((d["daily_unlocks"] - 150) / 120),
    }


def severity_label(s: float) -> str:
    return "On target" if s < 0.15 else "Mild" if s < 0.40 else "Moderate" if s < 0.70 else "High"


def pressure_label(p: float) -> str:
    return "Low" if p < 22 else "Moderate" if p < 40 else "Elevated" if p < 58 else "High"


def _value_and_target(key: str, d: dict):
    return {
        "sleep": (f"{d['sleep_hours_per_night']:g} h per night", "7-9 h per night"),
        "screen_time": (f"{d['avg_daily_usage_hours']:g} h per day", "4 h or less per day"),
        "stress": (d["stress_level"], "Low to Medium"),
        "activity": (f"{d['physical_activity_hours']:g} h per day", "about 1 h per day"),
        "phone_checking": (f"{d['daily_unlocks']} unlocks per day", "150 or fewer"),
        "workload": (f"{d['study_hours']:g} h per day", "5 h or less, with breaks"),
    }[key]


def _why(key: str, d: dict) -> str:
    v, t = _value_and_target(key, d)
    if key == "sleep" and d["sleep_hours_per_night"] > 9.5:
        return f"You sleep {v}, well above the usual {t}. Very long sleep can leave you feeling flat."
    return {
        "sleep": f"You sleep {v} against a target of {t}. Short sleep raises tension and lowers focus and mood.",
        "screen_time": f"Your screen time is {v} against a target of {t}. Heavy use crowds out rest, study and real-world contact.",
        "stress": f"You reported {v.lower()} stress. Ongoing high stress is the strongest signal in your profile.",
        "activity": f"Your physical activity is {v} against a target of {t}. Regular movement is one of the simplest stress buffers.",
        "phone_checking": f"You unlock your phone {v} (target: {t}). Constant checking fragments attention and adds background stress.",
        "workload": f"You study {v} (comfortable range: {t}). A heavy load without recovery is a common source of pressure.",
    }[key]


def _lead(d: dict) -> str:
    return {"High School": "a teacher or parent", "Undergraduate": "a tutor or course coordinator",
            "Graduate": "your supervisor or advisor"}.get(d.get("academic_level"), "a teacher or mentor")


def _steps(key: str, d: dict, sev: float) -> tuple[str, str, list[str]]:
    """(focus line, first step for today, further steps) built from the person's own numbers."""
    sleep, screen = d["sleep_hours_per_night"], d["avg_daily_usage_hours"]
    if key == "sleep":
        if sleep > 9.5:
            return ("Steady your sleep rhythm", "Set one wake-up time tomorrow and step outside for 10-15 minutes of morning light.",
                    ["Keep that wake-up time every day, weekends included.",
                     "Limit naps to 20 minutes and finish them before mid-afternoon.",
                     "If you still feel tired after long sleep for several weeks, mention it to a doctor."])
        gap = max(0.0, 7.5 - sleep)
        mins = round(gap * 60)
        days = math.ceil(max(mins, 20) / 20) * 3
        steps = [f"You are about {gap:g} h short of 7.5 h. Move lights-out 20 minutes earlier every 3 nights; "
                 f"you would reach your target in roughly {days} days.",
                 "Keep one wake-up time within an hour, weekends included.",
                 ("Your screen time is high, so put the phone on a charger across the room and stop screens 45 minutes before bed."
                  if screen > 5 or d["daily_unlocks"] > 180 else
                  "Charge your phone across the room and stop screens 45 minutes before bed."),
                 "Skip caffeine after mid-afternoon."]
        first = (f"Tonight, choose a lights-out time {min(max(mins, 20), 60)} minutes earlier than usual and start a "
                 "30-minute wind-down (dim lights, no scrolling in bed).")
        return "Protect your sleep window", first, steps
    if key == "screen_time":
        limit = max(2.0, round((screen - 1) * 2) / 2)
        platform, purpose = d["most_used_platform"], d["purpose_of_use"]
        if purpose in ("Entertainment", "News"):
            swap = "Swap one scrolling session a day for something offline: a walk, a call, a hobby."
        elif purpose == "Education":
            swap = "Much of your use is for learning, so keep it, but take a 20-second look-away break every 20 minutes."
        else:
            swap = "Batch social checks into two set times instead of staying logged in all day."
        return ("Take back your screen time",
                f"Open your phone's screen-time report today and set a {limit:g} h daily limit, starting with {platform}.",
                [f"Lower the limit by 30 minutes each week until you are near 4 h (you are at {screen:g} h).",
                 "Keep three phone-free blocks: meals, study time and the last hour before bed.", swap,
                 f"Mute {platform} notifications and move it off your home screen." if sev >= 0.6 else
                 f"Turn off non-essential {platform} notifications."])
    if key == "activity":
        h = d["physical_activity_hours"]
        first = ("Take a 10-minute walk after your next meal. It needs no equipment or planning." if h < 0.2 else
                 f"Add {15 if h < 0.5 else 10} minutes of movement to today: a brisk walk, stretching or a sport you like.")
        steps = ["Put three movement slots in your weekly calendar and treat them like classes.",
                 "Build up in 10-minute steps until you reach about 1 hour a day.",
                 (f"You study {d['study_hours']:g} h a day, so stand up and stretch for 5 minutes after every hour."
                  if d["study_hours"] >= 3 else "Stand up and stretch for 5 minutes after every hour of sitting.")]
        return "Add regular movement", first, steps
    if key == "workload":
        steps = ["Work in blocks of about 50 minutes on and 10 off, and set a hard stop time each evening.",
                 f"If the load is not sustainable, talk to {_lead(d)} about deadlines. Setting limits is normal."]
        if d["sleep_hours_per_night"] < 6.5:
            steps.insert(1, f"Do not pay for study time with sleep: you sleep {d['sleep_hours_per_night']:g} h, so protect 7 h first. Rested study is faster.")
        if d["physical_activity_hours"] < 0.5:
            steps.append("Use your 10-minute breaks to walk instead of scrolling; it doubles as your movement.")
        return ("Set boundaries around workload",
                f"Tomorrow morning pick your top three tasks out of your {d['study_hours']:g} study hours and drop or postpone the rest.", steps)
    if key == "phone_checking":
        awake = max(6.0, 24 - sleep)
        every = max(1, round(awake * 60 / max(d["daily_unlocks"], 1)))
        return ("Cut compulsive checking",
                f"You unlock your phone about once every {every} minutes while awake. Turn off badges and banner alerts today.",
                ["Check messages at set times, for example on the hour.",
                 "Use a focus mode during study and keep the phone in another room.",
                 "Before unlocking, take one slow breath and ask what you are looking for."])
    # stress
    steps = ["Do 2 minutes of slow breathing (in for 4, out for 6) three times a day.",
             "Write down what is worrying you, circle what you can control, and act on one item today.",
             "Tell a friend, family member or mentor how you are feeling. Sharing lightens the load."]
    if sev >= 0.65:
        steps.append("If stress stays this high for weeks, book a chat with a campus counsellor or doctor.")
    return ("Lower your stress load", "Next time tension rises, pause for 2 minutes of slow breathing (in for 4, out for 6).", steps)


def _combined(d: dict, sev: dict) -> list[dict]:
    """Cross-habit patterns. These are why two students with the same score can need different advice."""
    out = []
    late_phone = sev["screen_time"] >= 0.25 or sev["phone_checking"] >= 0.25
    if sev["sleep"] >= 0.25 and d["sleep_hours_per_night"] < 7 and late_phone:
        out.append({"title": "Phone habits may be shortening your sleep",
                    "text": "Short sleep together with heavy phone use often means screens are eating into your night. Start by moving the phone away from your bed."})
    if sev["workload"] >= 0.25 and d["sleep_hours_per_night"] < 6.5:
        out.append({"title": "You may be trading sleep for study time",
                    "text": "A heavy study load plus short sleep is a common pressure loop. Protecting sleep usually makes study time more effective."})
    if sev["workload"] >= 0.25 and sev["activity"] >= 0.5:
        out.append({"title": "Long study days with little movement",
                    "text": "Heavy workload and almost no physical activity leave stress nowhere to go. Short movement breaks inside study blocks are the smallest fix."})
    if sev["stress"] >= 0.65 and sev["sleep"] >= 0.25:
        out.append({"title": "Stress and short sleep tend to feed each other",
                    "text": "Improving sleep is often the fastest way to make stress feel more manageable, and easing stress makes sleep easier."})
    return out[:3]


def _strengths(d: dict) -> list[dict]:
    out = []
    if 7 <= d["sleep_hours_per_night"] <= 9:
        out.append(("Sleep", f"{d['sleep_hours_per_night']:g} h a night sits in the healthy 7-9 h range."))
    if d["avg_daily_usage_hours"] <= 4:
        out.append(("Screen time", f"{d['avg_daily_usage_hours']:g} h a day is well balanced."))
    if d["physical_activity_hours"] >= 1.0:
        out.append(("Physical activity", f"{d['physical_activity_hours']:g} h a day keeps your body and mood active."))
    if d["stress_level"] in ("Low", "Medium"):
        out.append(("Stress", f"You describe your stress as {d['stress_level'].lower()}, a good base to protect."))
    if d["daily_unlocks"] <= 150:
        out.append(("Phone habits", "You check your phone at a calm pace."))
    if 1.5 <= d["study_hours"] <= 5:
        out.append(("Study balance", f"{d['study_hours']:g} h of study a day is a sustainable load."))
    return [{"label": a, "detail": b} for a, b in out]


_KEEP = {
    "Sleep": "Keep bedtime and wake time within an hour of each other, weekends included. Sleep is one of your strongest assets.",
    "Screen time": "Hold your daily limit and keep the phone-free blocks at meals and before bed.",
    "Physical activity": "Protect your movement slots, especially in exam or busy weeks.",
    "Stress": "Keep a 2-minute breathing or journaling break in your day before stress builds up.",
    "Phone habits": "Keep notifications quiet and checking on your own schedule.",
    "Study balance": "Keep your study blocks and hard stop time; consistency beats cramming.",
}


def _maintenance(strengths: list[dict]) -> list[str]:
    tips = [_KEEP[s["label"]] for s in strengths if s["label"] in _KEEP][:3]
    tips.append("Do a 2-minute weekly check-in: how are my sleep, stress and screen time trending?")
    tips.append("Schedule offline time with people you like every week.")
    return tips[:5]


def analyze(d: dict, score: float, gains: dict | None = None) -> dict:
    """Build the full guidance object.
    d = validated inputs (snake_case, REAL values), score = model output, gains = model what-if gains."""
    gains = gains or {}
    sev = severities(d)
    impacts = {k: FACTORS[k][1] * s for k, s in sev.items()}
    pressure = round(sum(impacts.values()) / TOTAL_WEIGHT * 100, 1)

    reported = sorted((k for k in HABIT_KEYS if sev[k] >= REPORT_THRESHOLD), key=lambda k: impacts[k], reverse=True)
    total_reported = sum(impacts[k] for k in reported) or 1.0
    causes = []
    for rank, k in enumerate(reported, 1):
        v, t = _value_and_target(k, d)
        g = gains.get(k)
        causes.append({"key": k, "rank": rank, "label": FACTORS[k][0], "severity": round(sev[k], 2),
                       "severity_label": severity_label(sev[k]), "weight": FACTORS[k][1],
                       "impact": round(impacts[k], 1), "contribution_pct": round(impacts[k] / total_reported * 100),
                       "your_value": v, "target": t, "why": _why(k, d),
                       "model_gain": round(g, 2) if g is not None and g >= 0.05 else None})

    recs = []
    for c in causes[:3]:                                            # top 3 habit causes get a plan
        focus, first, steps = _steps(c["key"], d, c["severity"])
        recs.append({"key": c["key"], "priority": len(recs) + 1, "title": c["label"], "focus": focus,
                     "first_step": first, "steps": steps})
    if sev["stress"] >= 0.65:                                       # High / Very High stress always gets a relief plan
        focus, first, steps = _steps("stress", d, sev["stress"])
        recs.append({"key": "stress", "priority": len(recs) + 1, "title": "Stress relief", "focus": focus,
                     "first_step": first, "steps": steps})

    worst = max((sev[k] for k in HABIT_KEYS), default=0)
    if score < SUPPORT_SCORE or pressure >= SUPPORT_PRESSURE or worst >= SEVERE_HABIT:
        mode = "support"
    elif score >= HEALTHY_SCORE and pressure < HEALTHY_PRESSURE and worst < 0.4:
        mode = "maintain"
    else:
        mode = "balance"

    top = causes[0] if causes else None
    second = causes[1] if len(causes) > 1 else None
    tail = f", followed by {second['label'].lower()}" if second else ""
    if mode == "support" and top and score >= SUPPORT_SCORE and pressure < SUPPORT_PRESSURE:
        # the score itself is fine, but one habit is so far off target that it deserves attention now
        headline = "Your score is fine, but one habit needs attention"
        summary = (f"Your estimated score is {score:.1f}/10. However, {top['label'].lower()} is far outside its healthy range "
                   f"({top['contribution_pct']}% of your habit pressure){tail}. Fixing it now can protect your score.")
    elif mode == "support":
        headline = "Your habits point to high pressure right now"
        summary = (f"Your estimated score is {score:.1f}/10. The heaviest driver is {top['label'].lower()} "
                   f"({top['contribution_pct']}% of your habit pressure){tail}. Start there."
                   if top else f"Your estimated score is {score:.1f}/10, but no single habit stands out. The pressure may come from "
                               "things this tool cannot see (studies, relationships, health, money), so talking to someone can help.")
    elif mode == "balance":
        headline = "Balanced, with room to improve"
        summary = (f"Your estimated score is {score:.1f}/10. One or two small changes, starting with {top['label'].lower()}{tail}, could lift it."
                   if top else f"Your estimated score is {score:.1f}/10 and your habits look steady. Keep them consistent.")
        if top and score >= HEALTHY_SCORE:
            summary = (f"Your estimated score is {score:.1f}/10, which is healthy, but {top['label'].lower()} is a habit worth protecting "
                       "before it starts pulling the score down.")
    else:
        headline = "You are doing well. Keep it steady"
        summary = f"Your estimated score is {score:.1f}/10 and your habits support it. The goal now is to maintain what works."

    watch = [f"Keep an eye on {FACTORS[k][0].lower()}: it is close to the edge of its target range."
             for k in sorted(HABIT_KEYS, key=lambda k: impacts[k], reverse=True) if WATCH_THRESHOLD < sev[k] < REPORT_THRESHOLD][:2]
    strengths = _strengths(d)
    return {"version": GUIDANCE_VERSION, "method": "weighted habit analysis + model what-if", "is_causal": False,
            "mode": mode, "headline": headline, "summary": summary,
            "pressure_index": pressure, "pressure_label": pressure_label(pressure),
            "primary_root_cause": causes[0]["key"] if causes else None,
            "primary_root_cause_label": causes[0]["label"] if causes else None,
            "stress_signal": {"level": d["stress_level"], "severity": round(sev["stress"], 2)},
            "root_causes": causes, "recommendations": recs, "combined_insights": _combined(d, sev),
            "strengths": strengths, "maintenance": _maintenance(strengths) if mode != "support" else [],
            "watch": watch, "support_note": SUPPORT_NOTE if mode == "support" else None,
            "weights": [{"key": k, "label": lbl, "weight": w, "kind": kind} for k, (lbl, w, kind) in FACTORS.items()],
            "disclaimer": DISCLAIMER, "projected_score": None,
            "prescription": _prescription.build(d, score, sev, mode, causes)}


# ---- what-if: move ONE habit to its target and ask the trained model again -----------------------------
_WHATIF = {
    "sleep": ("Sleep_Hours_Per_Night", lambda v: max(v, 7.5)),
    "screen_time": ("Avg_Daily_Usage_Hours", lambda v: min(v, 4.0)),
    "phone_checking": ("Daily_Unlocks", lambda v: min(v, 150)),
    "activity": ("Physical_Activity_Hours", lambda v: max(v, 1.0)),
    "workload": ("Study_Hours", lambda v: min(v, 5.0)),
}


def model_gains(model, row, base_score: float, keys) -> dict:
    """Predicted score change if only that habit reached its target. Honest and small; may be ~0 or negative."""
    out = {}
    for k in keys:
        if k not in _WHATIF:
            continue
        col, fn = _WHATIF[k]
        alt = row.copy()
        alt[col] = fn(alt[col].iloc[0])
        try:
            out[k] = float(model.predict(alt)[0]) - base_score
        except Exception:
            out[k] = None
    return out


def projected_score(model, row, base_score: float, keys) -> float | None:
    """Score if the top root causes reached their targets TOGETHER (model estimate, not a promise)."""
    alt = row.copy()
    for k in keys:
        if k in _WHATIF:
            col, fn = _WHATIF[k]
            alt[col] = fn(alt[col].iloc[0])
    try:
        p = float(max(0, min(10, model.predict(alt)[0])))
    except Exception:
        return None
    return round(p, 2) if p >= base_score + 0.05 else None
