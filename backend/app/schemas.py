"""Shared data models: the contract between loader, solver, checker, explainer and API.

Change a model only after telling the team: everyone's code depends on these.
"""

from datetime import datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer

TIME_FMT = "%Y-%m-%d %H:%M"


def skill_rank(skill: str) -> int:
    """'L2' -> 2. A higher level can do lower-level work."""
    return int(skill.strip().upper().lstrip("L"))


# ---------- Input data (built by the loader) ----------

class Order(BaseModel):
    order_id: str
    product: str
    qty: int = Field(gt=0)
    due: datetime
    priority: int = Field(ge=1, le=3)
    customer: str
    customer_tier: int | None = None
    # Optional work-in-progress columns. movable=False -> this job is fixed exactly.
    wip_step: int | None = None
    wip_machine: str | None = None
    wip_operator: str | None = None
    wip_start: datetime | None = None
    wip_end: datetime | None = None
    movable: bool = True


class RoutingStep(BaseModel):
    product: str
    step: int = Field(ge=1)
    machines: list[str] = Field(min_length=1)  # parsed from "CNC-3|CNC-5"
    minutes_per_unit: float = Field(gt=0)
    skill_required: str


class Changeover(BaseModel):
    from_product: str
    to_product: str
    minutes: int = Field(ge=0)


class Operator(BaseModel):
    operator_id: str
    skill: str
    shift: str
    shift_start: time
    shift_end: time


class Disruption(BaseModel):
    event_id: str
    kind: Literal["breakdown", "rush_order"]
    at: datetime
    target: str  # machine (breakdown) or new order id (rush_order)
    duration_h: float | None = Field(default=None, gt=0)
    # Rush-order extras (our optional columns)
    product: str | None = None
    qty: int | None = None
    due: datetime | None = None
    priority: int | None = None
    customer: str | None = None


class Problem(BaseModel):
    orders: list[Order]
    routings: list[RoutingStep]
    changeovers: list[Changeover]
    operators: list[Operator]
    machines: list[str]
    plan_start: datetime


# ---------- Plans and results ----------

class Job(BaseModel):
    """One order step on one machine with one operator. A plan is a list of jobs."""
    order_id: str
    step: int
    product: str
    machine: str
    operator: str
    start: datetime
    end: datetime
    changed: bool = False

    @field_serializer("start", "end")
    def _fmt(self, value: datetime) -> str:
        return value.strftime(TIME_FMT)


class Blocked(BaseModel):
    """A machine unavailable window, e.g. a breakdown."""
    machine: str
    start: datetime
    end: datetime


class Weights(BaseModel):
    late: float = Field(default=10, ge=0)
    overtime: float = Field(default=3, ge=0)
    changeover: float = Field(default=1, ge=0)


class KPIs(BaseModel):
    late_orders: int
    total_lateness_h: float
    overtime_h: float
    changeovers: int
    moved_jobs: int = 0


class CheckResult(BaseModel):
    capacity_ok: bool
    skill_ok: bool
    changeover_ok: bool
    precedence_ok: bool
    eligibility_ok: bool
    shift_ok: bool
    wip_ok: bool
    breakdown_ok: bool
    violations: list[str] = []

    @computed_field
    @property
    def all_ok(self) -> bool:
        return all([self.capacity_ok, self.skill_ok, self.changeover_ok, self.precedence_ok,
                    self.eligibility_ok, self.shift_ok, self.wip_ok, self.breakdown_ok])


class Change(BaseModel):
    """One moved job. The reason is computed in code, never by the LLM."""
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    order_id: str
    step: int
    from_: str = Field(alias="from")  # e.g. "CNC-3 10:00"
    to: str
    reason_code: Literal["machine_down", "displaced_by_rush", "precedence", "rebalanced", "new_order"]
    facts: dict[str, Any] = {}


class SolveResult(BaseModel):
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN
    jobs: list[Job] = []
    kpis: KPIs | None = None
    solve_s: float


class LoadResult(BaseModel):
    rows_loaded: int
    rows_rejected: int
    status: str  # ok | partial | failed
    errors: list[str] = []


# ---------- API contract (guide section 6) ----------

AnswerType = Literal["plan", "replan", "infeasible", "explanation", "clarification_needed", "refused"]


class AnalyzeRequest(BaseModel):
    request: str = Field(min_length=1)
    disruption: list[Disruption] | None = None
    weights: Weights | None = None


class AnalyzeResponse(BaseModel):
    run_id: str
    answer_type: AnswerType
    summary: str
    plan: list[Job] = []
    kpis: KPIs | None = None
    changes: list[Change] = []
    validator: CheckResult | None = None
    tradeoff: str | None = None
    assumptions: list[str] = []
    limitations: list[str] = []


class TraceStep(BaseModel):
    agent: str
    tool: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    check: str | None = None
