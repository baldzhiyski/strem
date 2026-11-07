"""Race OS orchestration: context -> engine -> (AI) -> owning service.

Every build returns who produced the result (`origin`: engine or ai) and, when
the AI could not be used, the honest reason. Nothing is written as `ai` unless
the model actually produced it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.race import memory, store
from app.race.ai.client import AIUnavailable, RaceAI
from app.race.ai.models import LangChainRaceAI
from app.race.ai.personalize import ai_adapt, ai_brief
from app.race.clients import RaceServices
from app.race.context import RaceContext, assemble, render
from app.race.engine import adapt as engine_adapt
from app.race.engine.brief import build_brief
from app.race.engine.cockpit import build_cockpit
from app.race.enrich.conditions import race_conditions
from app.race.graph import build, review
from app.race.graph.team import team_answer

LAYERS = build.LAYERS


async def conditions_for(ctx: RaceContext) -> dict[str, Any] | None:
    event = ctx.event
    high = ctx.course.highest_m if ctx.course else None
    return await race_conditions(
        event.get("latitude"), event.get("longitude"), ctx.race_date, ctx.today, high
    )


async def load_context(
    services: RaceServices,
    mission_id: uuid.UUID,
    db: AsyncSession | None = None,
    user_id: uuid.UUID | None = None,
) -> RaceContext:
    """The athlete's context from the owning services; with a session and user it also
    carries their memory, so every AI path reads the same core context."""
    ctx = await assemble(services, mission_id, conditions=conditions_for)
    if db is not None and user_id is not None:
        ctx.memories = [memory.memory_out(m) for m in await memory.active(db, user_id)]
    return ctx


async def build_layers(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    kinds: list[str],
    *,
    use_ai: bool = True,
) -> list[dict[str, Any]]:
    """Race Lab and plan builds through the build graph."""
    ctx = await load_context(services, mission_id, db, user_id)
    return await build.run_builds(services, ai, ctx, kinds, use_ai=use_ai, context_text=render(ctx))


def _brief_digest(ctx: RaceContext) -> str:
    relevant = {
        "today": ctx.today.isoformat(),
        "plan": (ctx.plan or {}).get("version"),
        "totals": (ctx.progress or {}).get("totals"),
        "checkin": ctx.checkins[0] if ctx.checkins else None,
        "layers": {k: v.get("version") for k, v in ctx.layers.items()},
        "mission": ctx.mission.get("version"),
        "sessions": [s.get("id") for s in ctx.sessions[:3]],
        "memory": [(m["id"], m["updated_at"]) for m in ctx.memories],
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()


async def daily_brief(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """Today's brief, plus the race team's adjustment when training was missed (ai#44)."""
    ctx = await load_context(services, mission_id, db, user_id)
    brief = await _brief(ctx, ai, db, user_id, mission_id, refresh=refresh)
    proposal = await missed_proposal(ctx, ai, db, user_id, mission_id, services)
    if proposal is not None:
        brief["proposal"] = proposal
        actions = [a for a in brief.get("actions") or [] if a.get("target") != "proposal"]
        brief["actions"] = [
            {"title": "Review how the race team adjusted your week", "target": "proposal"},
            *actions,
        ][:6]
    return brief


async def _brief(
    ctx: RaceContext,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    engine = build_brief(ctx)
    digest = _brief_digest(ctx)
    if not refresh:
        cached = await store.cached_brief(db, user_id, mission_id, ctx.today, digest)
        if cached is not None:
            return {
                **cached.content,
                "origin": cached.origin,
                "model": cached.model,
                "ai_reason": None,
            }
    status = ai.status()
    if not status.available:
        return {
            **engine,
            "origin": "engine",
            "model": None,
            "ai_reason": status.reason,
            "conditions": ctx.conditions,
        }
    try:
        brief = await ai_brief(ai, render(ctx), engine)
    except AIUnavailable as exc:
        return {
            **engine,
            "origin": "engine",
            "model": None,
            "ai_reason": exc.reason,
            "conditions": ctx.conditions,
        }
    except (ValueError, KeyError, TypeError):
        return {
            **engine,
            "origin": "engine",
            "model": None,
            "ai_reason": "AI brief failed validation.",
            "conditions": ctx.conditions,
        }
    brief["conditions"] = ctx.conditions
    await store.save_brief(db, user_id, mission_id, ctx.today, digest, "ai", ai.model, brief)
    return {**brief, "origin": "ai", "model": ai.model, "ai_reason": None}


async def chat(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    message: str,
) -> dict[str, Any]:
    status = ai.status()
    if not status.available or not isinstance(ai, LangChainRaceAI):
        return {"available": False, "reason": status.reason, "message": None}
    ctx = await load_context(services, mission_id)
    known = await memory.active(db, user_id)
    ctx.memories = [memory.memory_out(m) for m in known]
    past = await store.history(db, user_id, mission_id, limit=30)
    turns = [
        {"role": row.role, "content": row.content}
        for row in past
        if row.role in ("user", "assistant")
    ]
    previous = turns[-1]["content"] if turns and turns[-1]["role"] == "assistant" else None
    turns.append({"role": "user", "content": message})

    try:
        # Remembering runs alongside the answer, so it adds no waiting (ai#59).
        answer, learned = await asyncio.gather(
            team_answer(ai, ctx, message, turns[:-1]), memory.extract(ai, known, message, previous)
        )
    except AIUnavailable as exc:
        return {"available": False, "reason": exc.reason, "message": None}
    asked = datetime.now(UTC)
    question = await store.add_message(db, user_id, mission_id, "user", message, created_at=asked)
    await memory.store_items(
        db, user_id, known, learned, source_ref=str(question.id), today=ctx.today
    )
    reply = await store.add_message(
        db,
        user_id,
        mission_id,
        "assistant",
        answer,
        ai.model,
        created_at=asked + timedelta(milliseconds=1),
    )
    await db.commit()
    return {
        "available": True,
        "reason": None,
        "message": {
            "id": str(reply.id),
            "role": "assistant",
            "content": reply.content,
            "model": reply.model,
            "created_at": reply.created_at.isoformat(),
        },
    }


def _guard_ai_changes(window: list[dict[str, Any]], adaptation: Any) -> list[dict[str, Any]]:
    by_id = {s["id"]: s for s in window}
    changes = []
    for change in adaptation.changes:
        session = by_id.get(change.session_id)
        if session is None or session["kind"] == "race":
            continue
        before = {
            k: session.get(k)
            for k in ("title", "duration_minutes", "distance_km", "intensity", "kind")
        }
        if change.change in ("rest", "remove"):
            after = {"title": "Rest", "duration_minutes": 0, "kind": "rest", "intensity": "rest"}
        else:
            after = dict(before)
            if change.title:
                after["title"] = change.title[:120]
            if change.intensity:
                after["intensity"] = change.intensity
            base = session.get("duration_minutes") or 0
            if change.duration_minutes is not None and base:
                after["duration_minutes"] = int(min(change.duration_minutes, base * 1.1))
            base_km = session.get("distance_km")
            if change.distance_km is not None and base_km:
                after["distance_km"] = round(min(change.distance_km, base_km * 1.1), 1)
            elif base_km and base and after["duration_minutes"] != base:
                # A new duration without a distance keeps the pace, not the old kilometres.
                after["distance_km"] = round(base_km * after["duration_minutes"] / base, 1)
        changes.append(
            {
                "session_id": session["id"],
                "date": session["date"],
                "change": change.change,
                "before": before,
                "after": after,
                "reason": change.reason[:300],
            }
        )
    return changes


def _review_graph(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    ctx: RaceContext,
    proposal_id: uuid.UUID,
    saver: Any,
) -> Any:
    """The review graph for one proposal, with this request's data and hooks."""

    async def drafter(state: review.ReviewState) -> dict[str, Any]:
        assert ctx.plan is not None
        plan = ctx.plan["content"]
        notes = [n for n in state.get("notes") or [] if n]
        proposal = state.get("base") or engine_adapt.adapt(plan, state["reason"], ctx.today)
        ask = state["reason"] + "".join(
            f"\nThe athlete reviewed the previous proposal and asked: {n}" for n in notes
        )
        status = ai.status()
        if not status.available:
            if notes:
                raise AIUnavailable(status.reason or "The AI race team is offline.")
            return {
                "draft": proposal,
                "origin": "engine",
                "model": None,
                "ai_reason": status.reason,
            }
        window = engine_adapt.window(plan, ctx.today, 7 if state["kind"] == "missed" else 14)
        try:
            adaptation = await ai_adapt(ai, render(ctx), ask, window)
            changes = _guard_ai_changes(window, adaptation)
        except AIUnavailable as exc:
            if notes:
                raise
            return {"draft": proposal, "origin": "engine", "model": None, "ai_reason": exc.reason}
        except (ValueError, KeyError, TypeError):
            if notes:
                raise AIUnavailable(
                    "The AI could not turn that into a valid change; try other words."
                ) from None
            reason = "The AI proposal failed validation; showing the engine's proposal."
            return {"draft": proposal, "origin": "engine", "model": None, "ai_reason": reason}
        if not changes and state["kind"] == "missed" and not notes:
            return {"draft": proposal, "origin": "engine", "model": None, "ai_reason": None}
        draft = {
            **proposal,
            "summary": adaptation.summary[:800],
            "safety_note": adaptation.safety_note or proposal.get("safety_note"),
            "changes": changes,
        }
        return {"draft": draft, "origin": "ai", "model": ai.model, "ai_reason": None}

    async def on_draft(state: review.ReviewState) -> None:
        assert ctx.plan is not None
        row = await db.get(store.RaceProposal, proposal_id)
        content = {
            **(state.get("draft") or {}),
            "reason": state["reason"],
            "notes": state.get("notes") or [],
        }
        if row is None:
            row = store.RaceProposal(
                id=proposal_id, user_id=user_id, mission_id=mission_id, created_at=datetime.now(UTC)
            )
            db.add(row)
        row.status = "pending"
        row.origin = state.get("origin") or "engine"
        row.model = state.get("model")
        row.plan_version = ctx.plan.get("version")
        row.content = content
        await db.commit()

    async def on_accept(_: review.ReviewState) -> None:
        row = await db.get(store.RaceProposal, proposal_id)
        assert row is not None
        await _apply_proposal(services, db, row)

    async def on_dismiss(_: review.ReviewState) -> None:
        row = await db.get(store.RaceProposal, proposal_id)
        assert row is not None
        row.status = "rejected"
        row.decided_at = datetime.now(UTC)
        await db.commit()

    return review.build_review(
        drafter=drafter,
        on_draft=on_draft,
        on_accept=on_accept,
        on_dismiss=on_dismiss,
        checkpointer=saver,
    )


async def _start_review(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    ctx: RaceContext,
    initial: review.ReviewState,
    proposal_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Draft a proposal and pause for the athlete's review."""
    pid = proposal_id or uuid.uuid4()
    graph = _review_graph(
        services, ai, db, user_id, mission_id, ctx, pid, await review.checkpointer()
    )
    await graph.ainvoke(initial, review.thread(pid))
    values = (await graph.aget_state(review.thread(pid))).values
    row = await db.get(store.RaceProposal, pid)
    assert row is not None
    await db.refresh(row)
    return proposal_out(row, values.get("ai_reason"))


async def propose_adaptation(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    reason: str,
) -> dict[str, Any]:
    ctx = await load_context(services, mission_id, db, user_id)
    if not ctx.plan:
        raise AppError(409, "plan_missing", "Build the training plan before adapting it.")
    return await _start_review(
        services, ai, db, user_id, mission_id, ctx, {"kind": "adapt", "reason": reason, "notes": []}
    )


async def missed_proposal(
    ctx: RaceContext,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    services: RaceServices,
) -> dict[str, Any] | None:
    """Skipped or missed sessions → one reviewed proposal; never a silent rewrite.

    A pending one is returned as is. Once the athlete decided on a proposal for
    the same missed sessions, the race team does not ask again.
    """
    if not ctx.plan or ctx.mission.get("state") != "active":
        return None
    earlier = await store.proposals(db, user_id, mission_id, category="missed")
    pending = next((p for p in earlier if p.status == "pending"), None)
    if pending is not None:
        if pending.plan_version == ctx.plan.get("version"):
            return proposal_out(pending)
        pending.status = "expired"  # the plan moved on; re-check below
        await db.commit()
    proposal = engine_adapt.missed(ctx.plan["content"], ctx.progress, ctx.today)
    if proposal is None:
        return None
    seen = set(proposal["trigger"]["missed"])
    if any(seen <= set((p.content.get("trigger") or {}).get("missed") or []) for p in earlier):
        return None
    initial: review.ReviewState = {
        "kind": "missed",
        "reason": "Missed training",
        "notes": [],
        "base": proposal,
    }
    return await _start_review(services, ai, db, user_id, mission_id, ctx, initial)


async def list_proposals(
    db: AsyncSession, user_id: uuid.UUID, mission_id: uuid.UUID, status: str | None
) -> list[dict[str, Any]]:
    rows = await store.proposals(db, user_id, mission_id)
    return [proposal_out(r) for r in rows if status is None or r.status == status]


def proposal_out(row: store.RaceProposal, ai_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "status": row.status,
        "origin": row.origin,
        "model": row.model,
        "plan_version": row.plan_version,
        "ai_reason": ai_reason,
        "created_at": row.created_at.isoformat(),
        **row.content,
    }


async def _apply_proposal(
    services: RaceServices, db: AsyncSession, row: store.RaceProposal
) -> None:
    """Write an accepted proposal to the plan, unless the plan moved on since."""
    plan = await services.plan(row.mission_id)
    if plan is None:
        raise AppError(409, "plan_missing", "The plan no longer exists.")
    if plan.get("version") != row.plan_version:
        row.status = "expired"
        await db.commit()
        raise AppError(409, "proposal_stale", "The plan changed since this proposal; ask again.")
    content = engine_adapt.apply_changes(plan["content"], row.content.get("changes") or [])
    await services.put_plan(
        row.mission_id,
        {
            "content": content,
            "origin": row.origin,
            "model": row.model,
            "inputs_digest": plan.get("inputs_digest"),
        },
    )
    row.status = "accepted"
    row.decided_at = datetime.now(UTC)
    await db.commit()


async def _pending(
    db: AsyncSession, user_id: uuid.UUID, mission_id: uuid.UUID, proposal_id: uuid.UUID
) -> store.RaceProposal:
    row = await db.get(store.RaceProposal, proposal_id)
    if row is None or row.user_id != user_id or row.mission_id != mission_id:
        raise AppError(404, "proposal_not_found", "Proposal not found.")
    if row.status != "pending":
        raise AppError(409, "proposal_decided", f"This proposal was already {row.status}.")
    return row


async def decide_proposal(
    services: RaceServices,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    proposal_id: uuid.UUID,
    accept: bool,
    ai: RaceAI,
) -> dict[str, Any]:
    row = await _pending(db, user_id, mission_id, proposal_id)
    ctx = await load_context(services, mission_id, db, user_id)
    graph = _review_graph(
        services, ai, db, user_id, mission_id, ctx, proposal_id, await review.checkpointer()
    )
    if await review.waiting_for_review(graph, proposal_id):
        await graph.ainvoke(
            Command(resume={"decision": "accept" if accept else "dismiss"}),
            review.thread(proposal_id),
        )
        await db.refresh(row)
        return proposal_out(row)
    # No review thread (stored before phase 4): decide directly.
    if accept:
        await _apply_proposal(services, db, row)
    else:
        row.status = "rejected"
        row.decided_at = datetime.now(UTC)
        await db.commit()
    return proposal_out(row)


async def adjust_proposal(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
    proposal_id: uuid.UUID,
    note: str,
) -> dict[str, Any]:
    """The athlete's words go back to the race team for a new draft; it pauses again."""
    row = await _pending(db, user_id, mission_id, proposal_id)
    status = ai.status()
    if not status.available:
        raise AppError(
            503,
            "ai_unavailable",
            f"Adjusting needs the AI race team. {status.reason or ''}".strip(),
        )
    ctx = await load_context(services, mission_id, db, user_id)
    if not ctx.plan:
        raise AppError(409, "plan_missing", "The plan no longer exists.")
    graph = _review_graph(
        services, ai, db, user_id, mission_id, ctx, proposal_id, await review.checkpointer()
    )
    try:
        if await review.waiting_for_review(graph, proposal_id):
            await graph.ainvoke(
                Command(resume={"decision": "adjust", "note": note}), review.thread(proposal_id)
            )
        else:
            kind = "missed" if row.content.get("category") == "missed" else "adapt"
            reason = str(row.content.get("reason") or "Adjust the plan")
            initial: review.ReviewState = {"kind": kind, "reason": reason, "notes": [note]}
            await graph.ainvoke(initial, review.thread(proposal_id))
    except AIUnavailable as exc:
        raise AppError(503, "ai_unavailable", exc.reason) from exc
    await db.refresh(row)
    return proposal_out(row)


async def cockpit(
    services: RaceServices,
    ai: RaceAI,
    db: AsyncSession,
    user_id: uuid.UUID,
    mission_id: uuid.UUID,
) -> dict[str, Any]:
    """The race-team cockpit (mobile#119): engine calls per specialist + what changed."""
    ctx = await load_context(services, mission_id, db, user_id)
    proposals = await list_proposals(db, user_id, mission_id, None)
    state = ai.status()
    return {
        **build_cockpit(ctx, proposals),
        "ai": {"available": state.available, "model": state.model, "reason": state.reason},
    }


async def knowledge(services: RaceServices, mission_id: uuid.UUID) -> dict[str, Any]:
    """What the race team can see — the athlete's view of their own context."""
    ctx = await load_context(services, mission_id)
    weeks = ctx.evidence_weeks()
    return {
        "mission": {"name": ctx.event.get("name"), "version": ctx.mission.get("version")},
        "sources": [{"label": s.get("label"), "last": s.get("last")} for s in ctx.sources],
        "recent_sessions": sum((w.get("volume") or {}).get("sessions", 0) for w in weeks),
        "recent_hours": round(sum((w.get("volume") or {}).get("hours", 0) for w in weeks), 1),
        "races_in_history": len(ctx.races),
        "race_activities_found": len(ctx.race_sessions),
        "checkins_recent": len(ctx.checkins),
        "has_course": ctx.course is not None,
        "has_profile": bool((ctx.profile or {}).get("is_started")),
        "has_weight": ctx.weight_kg is not None,
        "plan": {"version": ctx.plan.get("version"), "origin": ctx.plan.get("origin")}
        if ctx.plan
        else None,
        "layers": {
            k: {"version": v.get("version"), "origin": v.get("origin")}
            for k, v in ctx.layers.items()
        },
        "conditions": ctx.conditions,
        "missing": [
            label
            for present, label in (
                (bool(ctx.sources) or bool(ctx.sessions), "Connected sources or logged sessions"),
                (ctx.course is not None, "Course GPX"),
                (ctx.weight_kg is not None, "Body weight (for fueling grams)"),
                (bool(ctx.races), "Race history"),
                (bool(ctx.prep), "Preparation intake (availability, current volume)"),
                (ctx.event.get("latitude") is not None, "Race location (for conditions)"),
            )
            if not present
        ],
    }


STRAVA_SPORT = {
    "trail_running": "trail_running",
    "running": "road_running",
    "cycling": "cycling",
    "swimming": "swimming",
    "hiking": "hiking",
    "skiing": "nordic_skiing",
    "rowing": "rowing",
}


async def import_strava_races(services: RaceServices) -> dict[str, Any]:
    sessions = await services.race_sessions()
    items = []
    for s in sessions:
        if s.get("source") != "strava":
            continue
        day = str(s.get("logged_at", ""))[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        items.append(
            {
                "external_id": str(s["id"]),
                "name": (s.get("title") or f"Race on {day}")[:160],
                "race_date": day,
                "sport": STRAVA_SPORT.get(str(s.get("session_type")), "custom"),
                "distance_km": s.get("distance_km") or None,
                "elevation_gain_m": s.get("elevation_m") or None,
                "finish_minutes": s.get("elapsed_minutes") or s.get("duration_minutes"),
                "status": "finished",
            }
        )
    if not items:
        return {"created": 0, "updated": 0, "found": 0}
    result = await services.import_races(items[:200]) or {}
    return {
        "created": result.get("created", 0),
        "updated": result.get("updated", 0),
        "found": len(items),
    }
