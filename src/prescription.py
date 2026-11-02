"""Prescription-style plan that stays INSIDE the trained model's boundary.

Every item here is tied to an input the model was trained on (sleep, screen time, phone unlocks, physical activity,
study hours, stress level, plus platform / purpose / employment as context). Nothing is added from outside the dataset
(no food, supplements, medicines, caffeine, social or other topics). Where the model what-if is available, the expected
score change shown comes from the trained model itself (root_cause.model_gains), never from a guess.
"""
from __future__ import annotations

KEYS = ("sleep", "screen_time", "phone_checking", "activity", "workload", "stress")


def _g(x: float) -> str:
    return f"{x:g}"


def _status(sev: float) -> str:
    return "On target" if sev < 0.15 else "Mild" if sev < 0.40 else "Moderate" if sev < 0.70 else "High"


def build(d: dict, score: float, sev: dict, mode: str, causes: list[dict]) -> dict:
    sleep, screen = float(d["sleep_hours_per_night"]), float(d["avg_daily_usage_hours"])
    study, act = float(d["study_hours"]), float(d["physical_activity_hours"])
    unlocks, stress = int(d["daily_unlocks"]), d["stress_level"]
    platform, purpose = d.get("most_used_platform") or "your most-used app", d.get("purpose_of_use") or ""
    works = d.get("employment_status") and d["employment_status"] != "None (student only)"
    gain = {c["key"]: c.get("model_gain") for c in causes}
    order = [c["key"] for c in causes] + [k for k in KEYS if k not in {c["key"] for c in causes}]

    patient = (f"{d.get('age', '')}-year-old {str(d.get('gender', '')).lower()}, {d.get('academic_level', 'student')}"
               f"{', ' + str(d['employment_status']).lower() if works else ''}; main app {platform}"
               f"{' (' + purpose.lower() + ')' if purpose else ''}.").replace("  ", " ")
    band = "healthy range" if score >= 7 else "moderate range" if score >= 5 else "low range, needs support"
    impression = {
        "support": f"Model score {score:.1f}/10 ({band}). Your recorded habits show high pressure, so the plan starts with the few habits that weigh most.",
        "balance": f"Model score {score:.1f}/10 ({band}). Your habits are partly balanced; the changes below target what is furthest from its healthy range.",
        "maintain": f"Model score {score:.1f}/10 ({band}). Your recorded habits support your score; the plan is about keeping them steady.",
    }[mode]

    vitals = [
        {"label": "Sleep", "value": f"{_g(sleep)} h / night", "target": "7-9 h", "status": _status(sev["sleep"])},
        {"label": "Screen time", "value": f"{_g(screen)} h / day", "target": "4 h or less", "status": _status(sev["screen_time"])},
        {"label": "Phone unlocks", "value": f"{unlocks} / day", "target": "150 or fewer", "status": _status(sev["phone_checking"])},
        {"label": "Physical activity", "value": f"{_g(act)} h / day", "target": "about 1 h", "status": _status(sev["activity"])},
        {"label": "Study load", "value": f"{_g(study)} h / day", "target": "5 h or less", "status": _status(sev["workload"])},
        {"label": "Stress level", "value": stress, "target": "Low to Medium", "status": _status(sev["stress"])},
    ]

    # ---- doses: one per measured factor, sized from the person's own number ----
    screen_now = max(4.0, round((screen - 0.5) * 2) / 2) if screen > 4 else screen
    unlock_now = max(150, int(round(unlocks * 0.85 / 10) * 10)) if unlocks > 150 else unlocks
    move_now = round(min(1.0, act + (0.25 if act < 0.5 else 0.15)), 2)
    study_now = min(study, 5.0) if study > 5 else study
    sleep_now = min(7.5, round((sleep + 0.5) * 2) / 2) if sleep < 7 else sleep
    doses_raw = {
        "sleep": ("Sleep", f"{_g(sleep_now)} h per night this week" + (", then 7.5 h" if sleep_now < 7.5 else "") + "; same wake-up time daily" if sleep < 7 else
                  "Keep 7-9 h per night with a steady wake-up time", "Every night"),
        "screen_time": ("Screen time", f"No more than {_g(screen_now)} h per day this week" + (", lowering 30 min a week toward 4 h" if screen_now > 4 else ""), f"Check your screen-time report daily, starting with {platform}"),
        "phone_checking": ("Phone unlocks", f"About {unlock_now} unlocks per day this week" + (", then toward 150" if unlock_now > 150 else ""), "Notifications off for non-essential apps"),
        "activity": ("Physical activity", f"{int(round(move_now * 60))} min per day this week" + (", building toward 60 min" if move_now < 1 else ""), "Daily; short brisk walks count"),
        "workload": ("Study load", f"{_g(study_now)} h per day maximum, in 50-minute blocks with 10-minute breaks" if study > 5 else "Keep study within 5 h per day, in blocks with short breaks", "During study hours"),
        "stress": ("Stress", "Use a short calming pause (2 min slow breathing) whenever tension rises" if stress in ("High", "Very High", "Medium") else "Keep the habits that keep your stress low", "As needed, and once at midday"),
    }
    why = {
        "sleep": "Sleep carries the most weight in the trained model.", "screen_time": "Screen time is the other strongest signal in the trained model.",
        "phone_checking": "Frequent unlocking is one of the model's inputs.", "activity": "Activity is a measured habit with a healthy target of about 1 h.",
        "workload": "Study hours are a measured input; very long days leave less time for sleep and movement.",
        "stress": "Stress is the signal you reported; lowering the habits above usually lowers it too.",
    }
    doses = []
    for k in order:
        area, dose, when = doses_raw[k]
        g = gain.get(k)
        doses.append({"area": area, "dose": dose, "when": when, "why": why[k],
                      "effect": f"Model check: reaching target here alone would raise your predicted score by about {g:.2f}." if g else None,
                      "status": _status(sev[k])})

    routine = [
        {"slot": "Morning", "items": [f"Wake at the same time every day (sleep target {_g(sleep_now)}-7.5 h).",
                                      f"Do not open {platform} until you have started your first task."]},
        {"slot": "Daytime", "items": [("Study in 50/10 blocks with the phone out of reach." if study >= 3 else "Finish your main task before checking messages."),
                                       f"Fit in {int(round(move_now * 60))} min of movement.",
                                       f"Check messages at set times to keep unlocks near {unlock_now}."]},
        {"slot": "Evening", "items": [f"Look at today's screen-time report: aim for {_g(screen_now)} h or less.", "Stop study at a fixed time."]},
        {"slot": "Night", "items": ["Stop screens 45 minutes before bed and charge the phone away from the bed.",
                                     (f"Go to bed about 20 minutes earlier every 3 nights until you reach {_g(sleep_now)} h." if sleep < 7 else "Keep the same bedtime, weekends included.")]},
    ]

    pool = {
        "sleep": "Choose tonight's lights-out time (20 min earlier than usual) and set the wake-up alarm.",
        "screen_time": f"Open the screen-time report and set a daily limit of {_g(screen_now)} h, starting with {platform}.",
        "phone_checking": "Turn off badges and banners; check messages only at set times.",
        "activity": f"Do {int(round(move_now * 60))} min of walking or stretching.",
        "workload": "Pick your top 3 tasks, work in 50/10 blocks and stop at a fixed time.",
        "stress": "Do 2 minutes of slow breathing (in 4, out 6) three times today.",
    }
    week = [{"day": f"Day {i + 1}", "task": pool[order[i]]} for i in range(6)]
    week.append({"day": "Day 7", "task": "Review: which change was easiest? Keep it all, then tighten the limit that is still above target."})

    progression = [
        {"week": "Week 1", "goal": "Start small", "focus": f"Sleep {_g(sleep_now)} h, screen {_g(screen_now)} h, unlocks about {unlock_now}, movement {int(round(move_now * 60))} min."},
        {"week": "Week 2", "goal": "Tighten", "focus": "Lower screen time by 30 min and move bedtime earlier if sleep is still under 7 h. Add 10 min of movement."},
        {"week": "Week 3", "goal": "Hold", "focus": "Keep every limit for the full week, including weekends."},
        {"week": "Week 4", "goal": "Re-check", "focus": "Retake the MindPulse check-in and compare score, habit pressure and the six numbers above."},
    ]
    do = ["Change one habit at a time and keep it for a week.", "Use the same wake-up time every day.", "Check your screen-time report daily."]
    avoid = [f"Long unbroken sessions on {platform}.", "Scrolling in bed.", "Trading sleep for extra study hours."]
    if stress in ("High", "Very High"):
        do.append("Use the 2-minute breathing pause before stressful tasks.")
    track = ["Hours slept", "Screen time", "Phone unlocks", "Minutes of movement", "Study hours", "Stress level (Low / Medium / High / Very High)"]
    support = {
        "support": "Your inputs point to high pressure. Along with this plan, please talk to a trusted person, a campus counsellor or a doctor.",
        "balance": "You are close to balance. Stay consistent for two weeks, then re-check.",
        "maintain": "Keep your routine and re-check monthly.",
    }[mode]
    warning = ["Feeling very low or overwhelmed for more than two weeks, or struggling to cope with daily life.",
               "If you ever think of harming yourself, contact your local emergency number or a crisis line right away and tell someone near you."]
    return {"title": "Your wellness prescription", "patient": patient, "impression": impression, "vitals": vitals, "doses": doses,
            "routine": routine, "week_plan": week, "progression": progression, "do": do, "avoid": avoid, "track": track,
            "followup": "Retake the MindPulse check-in in 14 days and again at 4 weeks, and compare the same six numbers.",
            "warning_signs": warning, "support": support, "duration": "4 weeks",
            "note": "Every item is based only on the inputs the MindPulse model was trained on (sleep, screen time, phone unlocks, activity, study hours, stress, and your profile). It is lifestyle guidance, not medical advice."}
