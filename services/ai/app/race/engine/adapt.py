"""Rule-based plan adaptation for the next two weeks.

Recognizes the common situations (illness, pain/injury, lack of time, fatigue,
travel) from the athlete's words and proposes conservative changes. Health
situations always reduce load; nothing here increases load.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

PATTERNS = {
    "illness": r"\b(sick|ill|illness|flu|cold|covid|fever|virus|infection)\b",
    "injury": r"\b(injur\w*|pain|hurt\w*|knee|ankle|achilles|shin|hip|calf|plantar|strain|sprain)\b",
    "time": r"\b(busy|work|no time|less time|deadline|family|kids|schedule)\b",
    "travel": r"\b(travel\w*|trip|flight|away|vacation|holiday)\b",
    "fatigue": r"\b(tired|fatigue\w*|exhausted|sore|soreness|burn\w*|sleep|drained|heavy legs)\b",
}

SAFETY = {
    "illness": "Rest until symptoms clear; with fever or chest symptoms, no training at all. See a doctor if it lasts or worsens.",
    "injury": "Pain is a signal: stop activities that provoke it and get it assessed by a physio or doctor. STREM does not diagnose.",
}


def classify(reason: str) -> str:
    text = reason.lower()
    for key in ("illness", "injury", "travel", "time", "fatigue"):
        if re.search(PATTERNS[key], text):
            return key
    return "general"


def window(plan: dict[str, Any], today: date, days: int = 14) -> list[dict[str, Any]]:
    end = (today + timedelta(days=days)).isoformat()
    sessions = []
    for week in plan.get("weeks") or []:
        for s in week.get("sessions") or []:
            if today.isoformat() <= s["date"] <= end and s.get("status", "planned") == "planned":
                sessions.append(s)
    return sessions


def adapt(plan: dict[str, Any], reason: str, today: date) -> dict[str, Any]:
    """Returns {category, summary, safety_note, changes:[{session_id, change, before, after, reason}]}."""
    category = classify(reason)
    upcoming = [s for s in window(plan, today) if s["kind"] not in ("rest", "race")]
    changes: list[dict[str, Any]] = []

    def change(session: dict[str, Any], change_type: str, why: str, **after: Any) -> None:
        before = {
            k: session.get(k)
            for k in ("title", "duration_minutes", "distance_km", "intensity", "kind")
        }
        changes.append(
            {
                "session_id": session["id"],
                "date": session["date"],
                "change": change_type,
                "before": before,
                "after": {**before, **after}
                if change_type == "modify"
                else {"title": "Rest", "duration_minutes": 0, "kind": "rest", "intensity": "rest"},
                "reason": why,
            }
        )

    if category == "illness":
        for s in upcoming:
            days_out = (date.fromisoformat(s["date"]) - today).days
            if days_out < 4:
                change(
                    s, "rest", "Rest while you recover — training through illness delays the build."
                )
            elif s["kind"] in ("intervals", "tempo", "hills", "race_sim"):
                change(
                    s,
                    "modify",
                    "First days back: easy only.",
                    title="Easy return session",
                    intensity="easy",
                    kind="easy",
                    duration_minutes=int((s.get("duration_minutes") or 0) * 0.6),
                    distance_km=_scale(s.get("distance_km"), 0.6),
                )
            elif s.get("duration_minutes"):
                change(
                    s,
                    "modify",
                    "Ease back in at reduced volume.",
                    duration_minutes=int(s["duration_minutes"] * 0.7),
                    distance_km=_scale(s.get("distance_km"), 0.7),
                )
        summary = (
            "Recovery first: rest for the next few days, then return with easy, shorter sessions."
        )
    elif category == "injury":
        for s in upcoming:
            if s["sport"] in ("running", "trail_running", "hiking") or s["kind"] in (
                "intervals",
                "hills",
                "tempo",
                "race_sim",
            ):
                change(
                    s,
                    "modify",
                    "Replace impact and intensity with easy, pain-free cross-training until assessed.",
                    title="Easy cross-training (bike, swim or elliptical — pain-free only)",
                    intensity="easy",
                    kind="cross",
                    duration_minutes=int((s.get("duration_minutes") or 0) * 0.7),
                    distance_km=None,
                )
        summary = "Protect the injury: no impact or intensity for now. Cross-train only if it is pain-free, and get it assessed."
    elif category in ("time", "travel"):
        for s in upcoming:
            if s["kind"] in ("long", "race_sim", "back_to_back"):
                change(
                    s,
                    "modify",
                    "Keep the long session, shortened, so the key adaptation survives.",
                    duration_minutes=int((s.get("duration_minutes") or 0) * 0.75),
                    distance_km=_scale(s.get("distance_km"), 0.75),
                )
            elif s["kind"] == "easy":
                change(
                    s,
                    "modify",
                    "Short is better than skipped.",
                    duration_minutes=max(20, int((s.get("duration_minutes") or 0) * 0.5)),
                    distance_km=_scale(s.get("distance_km"), 0.5),
                )
        summary = "Less time: long and quality sessions are kept (shorter); easy sessions shrink. Consistency beats volume."
    elif category == "fatigue":
        rested = False
        for s in upcoming:
            if s["kind"] in ("intervals", "tempo", "hills"):
                change(
                    s,
                    "modify",
                    "Swap intensity for easy time while fatigue clears.",
                    title="Easy aerobic session",
                    intensity="easy",
                    kind="easy",
                )
            elif not rested and s["kind"] == "easy":
                change(s, "rest", "An extra rest day lets the fatigue clear.")
                rested = True
            elif s.get("duration_minutes"):
                change(
                    s,
                    "modify",
                    "Slightly lighter while you recover.",
                    duration_minutes=int(s["duration_minutes"] * 0.85),
                    distance_km=_scale(s.get("distance_km"), 0.85),
                )
        summary = "Fatigue signal: intensity becomes easy, one extra rest day, slightly lighter volume for two weeks."
    else:
        for s in upcoming:
            if s["kind"] in ("intervals", "tempo", "hills") and s.get("duration_minutes"):
                change(
                    s,
                    "modify",
                    "Slightly gentler while you tell us more.",
                    duration_minutes=int(s["duration_minutes"] * 0.85),
                )
        summary = "A gentle adjustment. Tell the race team more about what changed for a more specific plan."
    return {
        "category": category,
        "summary": summary,
        "safety_note": SAFETY.get(category),
        "changes": changes,
    }


def _scale(value: float | None, factor: float) -> float | None:
    return round(value * factor, 1) if value else value


def apply_changes(plan: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {c["session_id"]: c for c in changes}
    for week in plan.get("weeks") or []:
        for s in week.get("sessions") or []:
            c = by_id.get(s["id"])
            if not c or s["kind"] == "race":
                continue
            if c["change"] in ("rest", "remove"):
                s.update(
                    {
                        "sport": "rest",
                        "kind": "rest",
                        "title": "Rest",
                        "duration_minutes": 0,
                        "intensity": "rest",
                        "key": False,
                    }
                )
                for key in ("distance_km", "elevation_m", "structure", "fueling"):
                    s.pop(key, None)
            else:
                after = c["after"]
                for key in ("title", "duration_minutes", "intensity", "kind"):
                    if after.get(key) is not None:
                        s[key] = after[key]
                if "distance_km" in after:
                    old_km = s.get("distance_km")
                    if after["distance_km"] is None:
                        s.pop("distance_km", None)
                    else:
                        s["distance_km"] = after["distance_km"]
                        # Climbing shrinks and grows with the distance it was planned for.
                        if old_km and s.get("elevation_m"):
                            s["elevation_m"] = round(
                                s["elevation_m"] * after["distance_km"] / old_km
                            )
                if after.get("kind") == "cross":
                    s["sport"] = "other"
                    s.pop("elevation_m", None)
            s["purpose"] = (c.get("reason") or s.get("purpose") or "")[:600]
    return plan


QUALITY = ("intervals", "tempo", "hills", "race_sim")


def missed(
    plan: dict[str, Any], progress: dict[str, Any] | None, today: date
) -> dict[str, Any] | None:
    """Skipped or missed training in the last week → a lighter, rule-checked next week.

    Missed sessions are never made up. One missed easy session changes nothing;
    two or more (or a missed key session) ease the next week so the athlete does
    not jump back into what they skipped; three or more rebuild the rhythm with
    easy, slightly shorter training. Returns None when nothing needs to change.
    """
    since = today - timedelta(days=7)
    recent = [
        s
        for s in (progress or {}).get("sessions") or []
        if s.get("derived_status") in ("missed", "skipped")
        and since.isoformat() <= str(s.get("date")) < today.isoformat()
        and s.get("kind") not in ("rest", "race")
    ]
    key_missed = [s for s in recent if s.get("key")]
    if len(recent) < 2 and not key_missed:
        return None
    severe = len(recent) >= 3
    long_missed = any(s.get("kind") in ("long", "back_to_back", "race_sim") for s in recent)
    upcoming = [s for s in window(plan, today, 7) if s["kind"] not in ("rest", "race")]
    changes: list[dict[str, Any]] = []

    def modify(session: dict[str, Any], why: str, **after: Any) -> None:
        before = {
            k: session.get(k)
            for k in ("title", "duration_minutes", "distance_km", "intensity", "kind")
        }
        changes.append(
            {
                "session_id": session["id"],
                "date": session["date"],
                "change": "modify",
                "before": before,
                "after": {**before, **after},
                "reason": why,
            }
        )

    quality_kept = False
    for s in upcoming:
        minutes = s.get("duration_minutes") or 0
        if s["kind"] in QUALITY:
            if severe or quality_kept:
                modify(
                    s,
                    "Ease back in: easy aerobic time before intensity returns.",
                    title="Easy aerobic session",
                    kind="easy",
                    intensity="easy",
                )
            quality_kept = True
        elif s["kind"] in ("long", "back_to_back") and minutes and (severe or long_missed):
            factor = 0.85 if severe else 0.9
            modify(
                s,
                "Don't jump back to a longer long session than you've recently done.",
                duration_minutes=int(minutes * factor),
                distance_km=_scale(s.get("distance_km"), factor),
            )
        elif severe and s["kind"] == "easy" and minutes > 30:
            modify(
                s,
                "Rebuild the rhythm first.",
                duration_minutes=int(minutes * 0.85),
                distance_km=_scale(s.get("distance_km"), 0.85),
            )
    if not changes:
        return None
    titles = ", ".join(str(s.get("title")) for s in recent[:4])
    summary = f"You missed {len(recent)} session(s) this week ({titles}). Don't make them up — " + (
        "this week rebuilds the rhythm with easy, slightly shorter training before the plan carries on."
        if severe
        else "the plan carries on, a little lighter, so you don't jump straight back into what you skipped."
    )
    return {
        "category": "missed",
        "summary": summary,
        "safety_note": None,
        "changes": changes,
        "trigger": {"missed": sorted(str(s.get("id")) for s in recent), "since": since.isoformat()},
    }
