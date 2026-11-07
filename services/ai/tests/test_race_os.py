"""Race OS (docs#26): engine, AI guardrails, orchestration and enrichment.

All athletes, races and activities are synthetic. No network is used: owning
services are in-memory fakes and the model is scripted.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_session
from app.errors import AppError
from app.main import create_app
from app.race import service
from app.race.ai.client import AIStatus, AIUnavailable, UnavailableAI, get_race_ai, strict_schema
from app.race.ai.models import LangChainRaceAI
from app.race.ai.personalize import apply_layer_guardrails, apply_plan_edits
from app.race.ai.schemas import AdaptChange, AIAdaptation, AILayer, AIPlan
from app.race.context import RaceContext, render, summarize_course
from app.race.engine import adapt as engine_adapt
from app.race.engine.brief import build_brief
from app.race.engine.common import estimate_finish
from app.race.engine.fuel import build_fuel
from app.race.engine.gear import build_gear
from app.race.engine.logistics import build_logistics
from app.race.engine.plan import build_plan
from app.race.engine.strategy import build_strategy
from app.race.enrich import conditions as cond_mod
from app.race.enrich import media as media_mod
from app.race.graph.team import ROUTER_RULES
from app.race.router import get_race_services
from tests.support import TEST_SETTINGS, auth_header

TODAY = date(2026, 10, 23)


def mission(**event: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Synthetic Ridge 50K",
        "race_date": "2027-03-20",
        "timezone": "Europe/Sofia",
        "location_name": "Borovets",
        "distance_km": 50.0,
        "elevation_gain_m": 2400,
        "sport": "trail_running",
        "format": "single_day",
        "start_time": "07:00",
        "latitude": 42.27,
        "longitude": 23.6,
    }
    base.update(event)
    return {
        "id": str(uuid.uuid4()),
        "state": "active",
        "version": 3,
        "event": base,
        "goal": {"outcome": "finish_confidently", "priority": "A", "motivation": "Prove I can."},
        "preparation": {
            "experience": "some",
            "training_days_per_week": 5,
            "weekly_hours": 8,
            "long_session_day": "saturday",
            "home_location": "Sofia",
        },
    }


def ctx_for(m: dict[str, Any], **extra: Any) -> RaceContext:
    return RaceContext(mission=m, today=TODAY, **extra)


def items_of(layer: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for s in layer["sections"] for i in s["items"]]


# ── Engine ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "event",
    [
        {},
        {
            "name": "Synthetic Full Distance",
            "sport": "triathlon",
            "distance_km": 226.0,
            "elevation_gain_m": 1500,
        },
        {
            "name": "Synthetic City Marathon",
            "sport": "road_running",
            "distance_km": 42.2,
            "elevation_gain_m": 120,
        },
        {
            "name": "Synthetic Gran Fondo",
            "sport": "cycling",
            "distance_km": 160.0,
            "elevation_gain_m": 2800,
        },
        {
            "name": "Synthetic Lake Swim",
            "sport": "swimming",
            "distance_km": 5.0,
            "elevation_gain_m": None,
        },
        {
            "name": "Synthetic Traverse",
            "sport": "hiking",
            "distance_km": 120.0,
            "format": "multi_stage",
            "stages": 4,
            "end_date": "2027-03-23",
        },
        {
            "name": "Synthetic Everesting",
            "sport": "custom",
            "distance_km": 300.0,
            "elevation_gain_m": 8848,
            "legs": [{"discipline": "bike", "distance_km": 300}],
        },
    ],
)
def test_engine_builds_every_layer_for_every_sport(event: dict[str, Any]) -> None:
    ctx = ctx_for(mission(**event))
    plan = build_plan(ctx)
    sessions = [s for w in plan["weeks"] for s in w["sessions"]]
    ids = [s["id"] for s in sessions]
    assert len(ids) == len(set(ids))
    races = [s for s in sessions if s["kind"] == "race"]
    assert races and races[0]["date"] == ctx.event["race_date"]
    assert all(s["date"] >= TODAY.isoformat() for s in sessions)
    loads = [w["target_hours"] for w in plan["weeks"][1:-1]]
    for i in range(2, len(loads)):
        # Gradual: never far above the best of the previous two weeks (a lighter
        # week is followed by a return to the earlier loading level).
        assert loads[i] <= max(loads[i - 1], loads[i - 2]) * 1.25 + 0.5
    assert plan["weeks"][-1]["phase"] == "race"
    for builder in (build_fuel, build_gear, build_logistics, build_strategy):
        layer = builder(ctx)
        layer_ids = [i["id"] for i in items_of(layer)]
        assert layer["headline"] and len(layer_ids) == len(set(layer_ids))
        assert all(len(i) <= 64 for i in layer_ids)


def test_fuel_targets_scale_with_duration_heat_and_weight() -> None:
    long_hot = ctx_for(
        mission(), conditions={"temp_max_c": 30}, profile={"weight_kg": 70, "is_started": True}
    )
    fuel = build_fuel(long_hot)
    metrics = {m["label"]: m for m in fuel["metrics"]}
    assert metrics["Carbohydrate"]["value"] in ("60", "65", "75", "80")
    assert metrics["Fluid"]["value"].startswith("650")
    assert "Carb load" in metrics
    table = next(s for s in fuel["sections"] if s["id"] == "race-day")
    assert all(row["values"]["fluid_ml"] <= 850 for row in table["items"])
    short = build_fuel(
        ctx_for(
            mission(name="Synthetic 5K", sport="road_running", distance_km=5.0, elevation_gain_m=0)
        )
    )
    assert not any(s["id"] == "race-day" for s in short["sections"])
    assert any("hyponatraemia" in w for w in fuel["warnings"])
    assert not any(s["id"] == "dietary" for s in fuel["sections"])


def test_fuel_turns_dietary_needs_into_explicit_checks() -> None:
    profile = {
        "weight_kg": 70,
        "dietary_constraints": ["Lactose intolerant", " "],
        "is_started": True,
    }
    fuel = build_fuel(ctx_for(mission(), profile=profile))
    diet = next(s for s in fuel["sections"] if s["id"] == "dietary")
    titles = [i["title"] for i in diet["items"]]
    assert titles[0] == "Check every gel, drink and bar: Lactose intolerant"
    assert diet["items"][0]["id"] == "diet-lactose-intolerant"
    assert len(titles) == 2  # one check per real need + the aid-station question
    assert not any("respected" in a for a in fuel["assumptions"])  # no overclaim


def test_gear_adds_lights_for_night_and_logistics_respects_today() -> None:
    ultra = ctx_for(mission(distance_km=110.0, elevation_gain_m=6000, start_time="06:00"))
    gear = build_gear(ultra)
    ids = {i["id"]: i for i in items_of(gear)}
    assert ids["headlamp"]["priority"] == "critical"
    assert "find-kit-list" in ids
    soon = ctx_for(mission(race_date=(TODAY + timedelta(days=10)).isoformat()))
    logistics = build_logistics(soon)
    assert all(
        i.get("due_date", TODAY.isoformat()) >= TODAY.isoformat()
        for i in items_of(logistics)
        if i["id"] != "debrief"
    )
    morning = next(s for s in logistics["sections"] if s["id"] == "race-morning")
    assert morning["items"][-1]["when"] == "07:00"


def test_strategy_follows_course_terrain_and_sums_to_finish() -> None:
    course = {
        "course": {
            "distance_m": 10000,
            "ascent_m": 600,
            "descent_m": 600,
            "lowest_elevation_m": 1000,
            "highest_elevation_m": 1600,
        },
        "analysis": {
            "sections": [
                {
                    "start_distance_m": i * 100,
                    "end_distance_m": (i + 1) * 100,
                    "elevation_change_m": 10 if i < 50 else -10,
                    "average_grade_percent": 10 if i < 50 else -10,
                }
                for i in range(100)
            ],
            "sustained_runs": [
                {
                    "direction": "ascent",
                    "start_distance_m": 0,
                    "end_distance_m": 5000,
                    "net_elevation_change_m": 500,
                    "average_grade_percent": 10,
                }
            ],
        },
    }
    ctx = ctx_for(mission(distance_km=10.0, elevation_gain_m=600), course=summarize_course(course))
    strategy = build_strategy(ctx)
    rows = next(s for s in strategy["sections"] if s["id"] == "pacing")["items"]
    terrains = [r["title"].split("· ")[1] for r in rows]
    assert "climb" in terrains and "descent" in terrains
    assert rows[-1]["values"]["arrive"].replace(" ", "") in {
        x.replace(" ", "") for x in [_hm(estimate_finish(ctx).minutes)]
    }
    assert any(i["id"] == "your-why" for s in strategy["sections"] for i in s["items"])


def _hm(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


def test_brief_reports_today_session_risks_and_missing_course() -> None:
    m = mission()
    plan = build_plan(ctx_for(m))
    first_day = next(s for w in plan["weeks"] for s in w["sessions"] if s["kind"] != "rest")
    ctx = RaceContext(
        mission=m,
        today=date.fromisoformat(first_day["date"]),
        plan={"version": 1, "origin": "engine", "content": plan},
        checkins=[{"day": first_day["date"], "illness": True}],
    )
    brief = build_brief(ctx)
    assert brief["headline"].startswith("Today:")
    assert brief["risks"][0]["severity"] == "critical"
    assert any(a["target"] == "course" for a in brief["actions"])


def test_adaptation_rules_reduce_load_and_apply() -> None:
    m = mission()
    plan = build_plan(ctx_for(m))
    sick = engine_adapt.adapt(plan, "I have the flu and a fever", TODAY)
    assert sick["category"] == "illness" and sick["safety_note"]
    assert any(c["change"] == "rest" for c in sick["changes"])
    for change in sick["changes"]:
        if change["change"] == "modify" and change["before"]["duration_minutes"]:
            assert change["after"]["duration_minutes"] <= change["before"]["duration_minutes"]
    applied = engine_adapt.apply_changes(copy.deepcopy(plan), sick["changes"])
    rested = [
        s
        for w in applied["weeks"]
        for s in w["sessions"]
        if s["id"] == sick["changes"][0]["session_id"]
    ]
    assert rested[0]["kind"] in ("rest", "easy")
    assert engine_adapt.classify("my knee hurts on descents") == "injury"
    assert engine_adapt.classify("crazy week at work") == "time"


def test_ai_change_to_duration_scales_distance_and_climbing() -> None:
    # A 155-minute long run cut to 40 minutes must not keep 18.5 km and +350 m.
    long_run = {
        "id": "w3-sat",
        "date": "2026-11-07",
        "kind": "long",
        "sport": "trail_running",
        "title": "Long trail run",
        "duration_minutes": 155,
        "distance_km": 18.5,
        "elevation_m": 350,
        "intensity": "easy",
    }
    shorter = AIAdaptation(
        summary="Knee pain: keep it short and flat.",
        safety_note=None,
        changes=[
            AdaptChange(
                session_id="w3-sat",
                change="modify",
                title="Short flat easy run",
                purpose=None,
                duration_minutes=40,
                distance_km=None,
                intensity="very_easy",
                reason="Knee pain on descents.",
            )
        ],
    )
    changes = service._guard_ai_changes([long_run], shorter)
    assert changes[0]["after"]["duration_minutes"] == 40
    assert changes[0]["after"]["distance_km"] == 4.8  # same pace: 18.5 km * 40 / 155
    plan = {"weeks": [{"sessions": [copy.deepcopy(long_run)]}]}
    session = engine_adapt.apply_changes(plan, changes)["weeks"][0]["sessions"][0]
    assert (session["duration_minutes"], session["distance_km"]) == (40, 4.8)
    assert session["elevation_m"] == 91  # 350 m * 4.8 / 18.5

    # A distance the model gives is kept (within +10 %), and climbing follows it.
    shorter.changes[0].distance_km = 6.0
    changes = service._guard_ai_changes([long_run], shorter)
    assert changes[0]["after"]["distance_km"] == 6.0
    plan = {"weeks": [{"sessions": [copy.deepcopy(long_run)]}]}
    session = engine_adapt.apply_changes(plan, changes)["weeks"][0]["sessions"][0]
    assert session["elevation_m"] == 114


def test_render_labels_provenance_and_missing_sources() -> None:
    text = render(
        ctx_for(
            mission(),
            races=[
                {
                    "race_date": "2025-09-01",
                    "name": "Synthetic 30K",
                    "status": "finished",
                    "source": "athlete",
                    "lessons": ["Cramped at km 25"],
                }
            ],
        )
    )
    assert "## RACE MISSION [athlete]" in text
    assert "lesson: Cramped at km 25" in text
    assert "none (manual evidence only)" in text


# ── AI guardrails ────────────────────────────────────────────────────────────


def test_strict_schema_closes_objects_and_keeps_title_properties() -> None:
    schema = strict_schema(AILayer.model_json_schema())
    item = schema["$defs"]["AIItem"]
    assert item["additionalProperties"] is False
    assert "title" in item["properties"] and "title" in item["required"]
    assert "title" not in {k for k in item if k != "properties"}


def test_layer_guardrails_restore_engine_numbers_and_critical_items() -> None:
    ctx = ctx_for(mission(distance_km=110.0, elevation_gain_m=6000))
    engine = build_fuel(ctx)
    ai = copy.deepcopy(engine)
    ai["metrics"][0]["value"] = "140"  # unsafe carbohydrate target
    ai["warnings"] = []
    table = next(s for s in ai["sections"] if s["id"] == "race-day")
    table["items"][1]["values"] = {"carbs_g": 200, "fluid_ml": 2000, "sodium_mg": 0}
    rehearsals = next(s for s in ai["sections"] if s["id"] == "rehearsals")
    rehearsals["items"] = [i for i in rehearsals["items"] if i.get("priority") != "critical"]
    guarded = apply_layer_guardrails("fuel", engine, ai)
    assert guarded["metrics"][0]["value"] == engine["metrics"][0]["value"]
    assert set(engine["warnings"]) <= set(guarded["warnings"])
    row = next(s for s in guarded["sections"] if s["id"] == "race-day")["items"][1]
    assert row["values"]["fluid_ml"] <= 850
    assert any(i["id"] == "gut-training" for i in items_of(guarded))


def test_plan_edits_are_clamped_and_never_touch_the_past_or_race() -> None:
    ctx = ctx_for(mission())
    engine = build_plan(ctx)
    sessions = [s for w in engine["weeks"] for s in w["sessions"] if s.get("duration_minutes")]
    target, race = sessions[0], next(s for s in sessions if s["kind"] == "race")
    edits = AIPlan.model_validate(
        {
            "headline": "Your mountain plan",
            "summary": "Tailored.",
            "principles": [],
            "warnings": ["Ankle history: keep descents controlled."],
            "assumptions": [],
            "week_notes": [],
            "session_edits": [
                {
                    "id": target["id"],
                    "title": "Hill strides",
                    "purpose": None,
                    "structure": None,
                    "fueling": None,
                    "terrain": None,
                    "duration_minutes": target["duration_minutes"] * 3,
                    "distance_km": None,
                    "elevation_m": None,
                },
                {
                    "id": race["id"],
                    "title": None,
                    "purpose": None,
                    "structure": None,
                    "fueling": None,
                    "terrain": None,
                    "duration_minutes": 1,
                    "distance_km": 1.0,
                    "elevation_m": None,
                },
            ],
        }
    )
    result = apply_plan_edits(engine, edits, TODAY)
    out = {s["id"]: s for w in result["weeks"] for s in w["sessions"]}
    assert out[target["id"]]["title"] == "Hill strides"
    assert out[target["id"]]["duration_minutes"] <= round(target["duration_minutes"] * 1.25)
    assert out[race["id"]]["duration_minutes"] == race["duration_minutes"]
    assert "Ankle history: keep descents controlled." in result["warnings"]


# ── Orchestration with fake services and a scripted model ───────────────────


class FakeServices:
    def __init__(self, m: dict[str, Any]) -> None:
        self.m = m
        self.plan_doc: dict[str, Any] | None = None
        self.layer_docs: dict[str, dict[str, Any]] = {}
        self.reject_ai = False

    async def mission(self, mission_id: uuid.UUID) -> dict[str, Any]:
        if str(mission_id) != self.m["id"]:
            raise AppError(404, "mission_not_found", "Race Mission not found.")
        return self.m

    async def missions(self) -> list[dict[str, Any]]:
        return [self.m]

    async def user(self) -> dict[str, Any] | None:
        return {"display_name": "Synthetic Athlete"}

    async def athlete_profile(self) -> dict[str, Any] | None:
        return {"is_started": True, "weight_kg": 68}

    async def races(self) -> list[dict[str, Any]]:
        return []

    async def race_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": str(uuid.uuid4()),
                "source": "strava",
                "logged_at": "2026-05-02T06:00:00Z",
                "title": "Synthetic Trail 30",
                "session_type": "trail_running",
                "distance_km": 30.1,
                "elevation_m": 1500,
                "duration_minutes": 240,
                "elapsed_minutes": 255,
            }
        ]

    async def layers(self, mission_id: uuid.UUID) -> dict[str, dict[str, Any]]:
        return dict(self.layer_docs)

    async def plan(self, mission_id: uuid.UUID) -> dict[str, Any] | None:
        return self.plan_doc

    async def progress(self, mission_id: uuid.UUID) -> dict[str, Any] | None:
        return None

    async def course(self, mission_id: uuid.UUID) -> dict[str, Any] | None:
        return None

    async def sessions(self, limit: int = 120) -> list[dict[str, Any]]:
        return []

    async def checkins(self) -> list[dict[str, Any]]:
        return []

    async def sources(self) -> list[dict[str, Any]]:
        return []

    async def recovery(self) -> list[dict[str, Any]]:
        return []

    async def put_plan(self, mission_id: uuid.UUID, body: dict[str, Any]) -> dict[str, Any]:
        if self.reject_ai and body["origin"] == "ai":
            raise AppError(422, "validation_error", "bad")
        version = (self.plan_doc or {}).get("version", 0) + 1
        self.plan_doc = {**body, "version": version, "mission_id": self.m["id"]}
        return self.plan_doc

    async def put_layer(
        self, mission_id: uuid.UUID, kind: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        if self.reject_ai and body["origin"] == "ai":
            raise AppError(422, "validation_error", "bad")
        version = self.layer_docs.get(kind, {}).get("version", 0) + 1
        self.layer_docs[kind] = {**body, "kind": kind, "version": version}
        return self.layer_docs[kind]

    async def import_races(self, items: list[dict[str, Any]]) -> dict[str, Any] | None:
        return {"created": len(items), "updated": 0}


class EchoChat(BaseChatModel):
    """The race team's chat model in tests: answers the newest question."""

    @property
    def _llm_type(self) -> str:
        return "echo"

    def bind_tools(self, tools: Any, **_: Any) -> Any:
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **_: Any
    ) -> ChatResult:
        asked = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        reply = AIMessage(content=f"Answer to: {asked.text}")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class ScriptedAI(LangChainRaceAI):
    model = "claude-opus-5-5"

    def __init__(self) -> None:
        super().__init__(EchoChat(), self.model, "openai")
        self._reasoning = False
        self.calls: list[str] = []
        self.fail: str | None = None

    def status(self) -> AIStatus:
        return AIStatus(False, self.model, self.fail) if self.fail else super().status()

    async def complete_json(
        self, *, rules: str, context: str, prompt: str, schema: dict[str, Any], **_: Any
    ) -> dict[str, Any]:
        if self.fail:
            raise AIUnavailable(self.fail)
        task = prompt.splitlines()[0]
        self.calls.append(task)
        if rules == ROUTER_RULES:
            return {"specialists": ["coach"], "why": "scripted"}
        if rules.startswith("You maintain the long-term memory"):
            # Athlete memory (ai#59): remember an injury when one is mentioned.
            said = prompt.rsplit("message:\n", 1)[-1]
            if "knee" not in said.lower():
                return {"items": []}
            return {
                "items": [
                    {
                        "kind": "injury",
                        "text": "Left knee hurts on long descents",
                        "confidence": 0.9,
                        "replaces": None,
                    }
                ]
            }
        assert "RACE MISSION" in context and schema["additionalProperties"] is False
        if "training plan" in task:
            return {
                "headline": "Built for the ridge",
                "summary": "Tailored to your climbs.",
                "principles": [],
                "warnings": [],
                "assumptions": [],
                "week_notes": [],
                "session_edits": [],
            }
        if "race brief" in task:
            return {
                "headline": "Climb strong today",
                "message": "Evidence-based.",
                "evidence": [],
                "risks": [],
                "actions": [{"title": "Upload the course GPX", "target": "course"}],
            }
        if "adapt" in task:
            if "reviewed the previous proposal and asked:" in prompt:
                return {"summary": "Adjusted as you asked.", "safety_note": None, "changes": []}
            return {
                "summary": "Rest two days.",
                "safety_note": "See a doctor if fever persists.",
                "changes": [],
            }
        return {
            "headline": "Personalized layer",
            "summary": "Uses your history.",
            "metrics": [],
            "sections": [
                {
                    "id": "extra",
                    "title": "Athlete-specific",
                    "kind": "checklist",
                    "description": None,
                    "columns": None,
                    "items": [
                        {
                            "id": "Bad Id!",
                            "title": "Pack salt tabs — you cramped before",
                            "detail": None,
                            "when": None,
                            "due_date": "2020-01-01",
                            "quantity": None,
                            "tag": None,
                            "priority": "high",
                            "values": None,
                        }
                    ],
                }
            ],
            "warnings": [],
            "assumptions": [],
            "personalization_notes": ["Added salt from race history"],
        }

    async def complete_text(
        self, *, rules: str, context: str, messages: list[dict[str, str]], **_: Any
    ) -> str:
        if self.fail:
            raise AIUnavailable(self.fail)
        return f"Answer to: {messages[-1]['content']}"


@asynccontextmanager
async def race_app(fake: FakeServices, ai: Any) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    app.dependency_overrides[get_race_services] = lambda: fake
    app.dependency_overrides[get_race_ai] = lambda: ai
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def no_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(ctx: RaceContext) -> None:
        return None

    monkeypatch.setattr(service, "conditions_for", none)


def test_build_all_layers_with_ai_then_honest_engine_fallback() -> None:
    async def scenario() -> None:
        m = mission(race_date=(datetime.now(UTC).date() + timedelta(weeks=16)).isoformat())
        fake, ai = FakeServices(m), ScriptedAI()
        headers = auth_header(uuid.uuid4())
        async with race_app(fake, ai) as client:
            built = await client.post(f"/v1/ai/race/{m['id']}/build", headers=headers, json={})
            assert built.status_code == 200, built.text
            results = {r["kind"]: r for r in built.json()["results"]}
            assert set(results) == {"plan", "fuel", "gear", "logistics", "strategy"}
            assert all(
                r["origin"] == "ai" and r["model"] == "claude-opus-5-5" for r in results.values()
            )
            assert fake.plan_doc and fake.plan_doc["content"]["headline"] == "Built for the ridge"
            extra = next(
                s for s in fake.layer_docs["fuel"]["content"]["sections"] if s["id"] == "extra"
            )
            assert extra["items"][0]["id"] == "pack-salt-tabs-you-cramped-before"
            assert extra["items"][0]["due_date"] >= datetime.now(UTC).date().isoformat()
            # Engine warnings survive personalization.
            assert fake.layer_docs["fuel"]["content"]["warnings"]

            ai.fail = "The Anthropic account has no credit left."
            rebuilt = await client.post(
                f"/v1/ai/race/{m['id']}/layers/gear/build", headers=headers, json={}
            )
            body = rebuilt.json()
            assert body["origin"] == "engine" and body["model"] is None
            assert "credit" in body["ai_reason"]
            status = await client.get("/v1/ai/race/status", headers=headers)
            assert status.json()["available"] is False

            ai.fail = None
            fake.reject_ai = True
            saved = await client.post(
                f"/v1/ai/race/{m['id']}/layers/logistics/build", headers=headers, json={}
            )
            assert saved.json()["origin"] == "engine" and "rejected" in saved.json()["ai_reason"]

            missing = await client.post(
                f"/v1/ai/race/{uuid.uuid4()}/build", headers=headers, json={}
            )
            assert missing.status_code == 404

    asyncio.run(scenario())


def test_brief_chat_adaptation_and_strava_import_flows() -> None:
    async def scenario() -> None:
        m = mission(race_date=(datetime.now(UTC).date() + timedelta(weeks=12)).isoformat())
        fake, ai = FakeServices(m), ScriptedAI()
        headers = auth_header(uuid.uuid4())
        async with race_app(fake, ai) as client:
            await client.post(
                f"/v1/ai/race/{m['id']}/build",
                headers=headers,
                json={"layers": ["plan"], "use_ai": False},
            )
            assert fake.plan_doc and fake.plan_doc["origin"] == "engine"

            brief = (await client.get(f"/v1/ai/race/{m['id']}/brief", headers=headers)).json()
            assert brief["origin"] == "ai" and brief["headline"] == "Climb strong today"
            cached = (await client.get(f"/v1/ai/race/{m['id']}/brief", headers=headers)).json()
            assert cached["origin"] == "ai" and len([c for c in ai.calls if "race brief" in c]) <= 1

            reply = (
                await client.post(
                    f"/v1/ai/race/{m['id']}/chat",
                    headers=headers,
                    json={"message": "Am I on track?"},
                )
            ).json()
            assert reply["available"] and reply["message"]["content"] == "Answer to: Am I on track?"
            history = (await client.get(f"/v1/ai/race/{m['id']}/chat", headers=headers)).json()
            assert [i["role"] for i in history["items"]] == ["user", "assistant"]

            ai.fail = "AI offline"
            offline = (
                await client.post(
                    f"/v1/ai/race/{m['id']}/chat", headers=headers, json={"message": "Hello?"}
                )
            ).json()
            assert offline == {"available": False, "reason": "AI offline", "message": None}
            proposal = (
                await client.post(
                    f"/v1/ai/race/{m['id']}/adapt",
                    headers=headers,
                    json={"reason": "I caught a cold with fever"},
                )
            ).json()
            assert proposal["origin"] == "engine" and proposal["category"] == "illness"
            assert proposal["changes"]
            accepted = await client.post(
                f"/v1/ai/race/{m['id']}/proposals/{proposal['id']}/accept", headers=headers
            )
            assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
            again = await client.post(
                f"/v1/ai/race/{m['id']}/proposals/{proposal['id']}/reject", headers=headers
            )
            assert again.status_code == 409

            stale = (
                await client.post(
                    f"/v1/ai/race/{m['id']}/adapt",
                    headers=headers,
                    json={"reason": "busy week at work"},
                )
            ).json()
            fake.plan_doc["version"] += 1
            expired = await client.post(
                f"/v1/ai/race/{m['id']}/proposals/{stale['id']}/accept", headers=headers
            )
            assert expired.status_code == 409 and expired.json()["code"] == "proposal_stale"

            imported = (
                await client.post("/v1/ai/race/history/import-strava", headers=headers)
            ).json()
            assert imported == {"created": 1, "updated": 0, "found": 1}
            knowledge = (
                await client.get(f"/v1/ai/race/{m['id']}/knowledge", headers=headers)
            ).json()
            assert "Course GPX" in knowledge["missing"] and knowledge["has_weight"] is True
            cockpit = (await client.get(f"/v1/ai/race/{m['id']}/cockpit", headers=headers)).json()
            assert [s["role"] for s in cockpit["specialists"]][:3] == ["coach", "fuel", "course"]
            assert cockpit["ai"]["available"] is False and sum(cockpit["summary"].values()) == 6

    asyncio.run(scenario())


def test_unavailable_ai_reports_reason_without_key() -> None:
    ai = UnavailableAI()
    assert ai.status().available is False and "key" in (ai.status().reason or "")


# ── Enrichment parsing (no network) ──────────────────────────────────────────


def test_media_search_ranks_event_first_and_excludes_no_derivatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(url: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
        if "openverse" in url:
            return {
                "results": [
                    {
                        "id": "ov1",
                        "url": "https://live.staticflickr.com/a_b.jpg",
                        "thumbnail": "https://api.openverse.org/t",
                        "title": "Ridge",
                        "creator": "x",
                        "license": "by-nd",
                        "license_version": "2.0",
                        "width": 2000,
                        "height": 1000,
                    }
                ]
            }
        search = params["gsrsearch"] if params else ""
        page = {
            "pageid": hash(search) % 10000,
            "title": f"File:{search[:60]}.jpg",
            "imageinfo": [
                {
                    "url": (
                        "https://upload.wikimedia.org/wikipedia/commons/a/ab/"
                        f"{abs(hash(search)) % 999}.jpg?utm_source=x"
                    ),
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:x.jpg",
                    "width": 3000,
                    "height": 2000,
                    "mime": "image/jpeg",
                    "extmetadata": {
                        "Artist": {"value": "<a href='u'>Photographer</a>"},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                    },
                }
            ],
        }
        return {"query": {"pages": {"1": page}}}

    monkeypatch.setattr(media_mod, "get_json", fake_get)
    items = asyncio.run(
        media_mod.search_media("Synthetic Ridge 50K", "Borovets, Bulgaria", "trail_running")
    )
    assert items[0]["depicts"] == "event" and items[0]["provider"] == "wikimedia"
    assert all(i["provider"] != "openverse" for i in items)  # by-nd excluded
    assert items[0]["creator"] == "Photographer"
    assert "/thumb/" in items[0]["thumb_url"] and "utm_source" not in items[0]["url"]
    # Commons only serves its standard thumbnail widths
    assert "/500px-" in items[0]["thumb_url"] and "/1280px-" in items[0]["url"]


def test_slow_openverse_is_paused_after_one_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_get(url: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
        calls.append(url)
        if "openverse" in url:
            raise httpx.ReadTimeout("slow")
        return {"query": {"pages": {}}}

    monkeypatch.setattr(media_mod, "get_json", fake_get)
    monkeypatch.setitem(media_mod._OPENVERSE, "paused_until", 0.0)
    asyncio.run(media_mod.search_media("Synthetic 50K", None, None))
    asyncio.run(media_mod.search_media("Synthetic 50K", None, None))
    assert sum("openverse" in url for url in calls) == 1  # the second search skips it


def test_media_ranking_follows_the_race_type() -> None:
    words = media_mod.SPORT_TERMS["trail_running"][1]

    def photo(title: str, depicts: str) -> dict[str, Any]:
        return {"title": title, "depicts": depicts, "width": 3000, "height": 2000}

    shuffled = [
        photo("Vitosha Charter", "event"),
        photo("Sofia Glacier, Caucasus", "location"),
        photo("Trail runner on a ridge", "atmosphere"),
        photo("Vitosha view, drawing", "location"),
        photo("Synthetic Ridge trail race 2024", "event"),
        photo("Runners above Sofia, Bulgaria", "location"),
    ]
    ranked = sorted(shuffled, key=lambda item: media_mod._rank(item, words))
    assert [p["title"] for p in ranked] == [
        "Synthetic Ridge trail race 2024",
        "Runners above Sofia, Bulgaria",
        "Trail runner on a ridge",
        "Sofia Glacier, Caucasus",
        "Vitosha Charter",  # documents and artwork last
        "Vitosha view, drawing",
    ]
    # No sport given: event, location, atmosphere as before.
    assert media_mod._rank(photo("Anything", "event"), ()) == 0


def test_media_search_only_labels_photos_that_name_the_race_or_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_commons(query: str, depicts: str, limit: int = 12) -> list[dict[str, Any]]:
        title = "Helvellyn Trail race" if depicts == "event" else "Plovdiv old town"
        return [
            {
                "url": f"https://x/{query}.jpg",
                "title": title,
                "depicts": depicts,
                "width": 3000,
                "height": 2000,
            }
        ]

    async def no_openverse(query: str, depicts: str, limit: int = 10) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(media_mod, "search_commons", fake_commons)
    monkeypatch.setattr(media_mod, "search_openverse", no_openverse)
    items = asyncio.run(
        media_mod.search_media("Plovdiv Hills Ultra 44K", "Markovo, Plovdiv", "trail_running")
    )
    labels = {(i["title"], i["depicts"]) for i in items}
    # A trail race elsewhere is atmosphere, not this race; the city photo is the place.
    assert ("Helvellyn Trail race", "atmosphere") in labels
    assert ("Plovdiv old town", "location") in labels
    assert all(i["depicts"] != "event" for i in items)


def test_media_ranking_prefers_frames_that_fit_a_hero() -> None:
    assert media_mod._cover_fit({"width": 3000, "height": 2000}) == 0
    assert media_mod._cover_fit({"width": 11429, "height": 2400}) == 1  # panorama
    assert media_mod._cover_fit({"width": 2000, "height": 3000}) == 2
    assert media_mod._cover_fit({"width": None, "height": None}) == 1


def test_seasonal_conditions_average_past_years(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(url: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
        return {
            "elevation": 1300,
            "daily": {
                "time": ["a", "b", "c"],
                "temperature_2m_max": [20.0, 22.0, 24.0],
                "temperature_2m_min": [8.0, 9.0, 10.0],
                "precipitation_sum": [0.0, 5.0, 0.0],
                "wind_speed_10m_max": [10.0, 12.0, 14.0],
                "sunrise": ["2025-03-20T06:30", "2025-03-21T06:28", "2025-03-22T06:26"],
                "sunset": ["2025-03-20T18:40", "2025-03-21T18:41", "2025-03-22T18:42"],
            },
        }

    monkeypatch.setattr(cond_mod, "get_json", fake_get)
    cond = asyncio.run(
        cond_mod.race_conditions(42.27, 23.6, date(2027, 3, 21), TODAY, course_high_m=2900)
    )
    assert cond is not None and cond["kind"] == "seasonal" and cond["years"] == 5
    assert cond["temp_max_c"] == 22.0 and cond["sunset"] == "2025-03-21T18:41"
    assert "colder up high" in cond["altitude_note"]
    assert cond["summary"].startswith("Typical for the date")
