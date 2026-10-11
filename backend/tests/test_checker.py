from datetime import datetime, time
import pytest

from app.checker import compute_kpis, validate_plan
from app.schemas import (
    Blocked,
    Changeover,
    Job,
    Operator,
    Order,
    Problem,
    RoutingStep,
)


@pytest.fixture
def base_problem() -> Problem:
    """A minimal valid production problem with two orders, two machines, and two operators."""
    orders = [
        Order(
            order_id="O-101",
            product="P-A",
            qty=10,
            due=datetime(2026, 10, 12, 12, 0),
            priority=1,
            customer="Acme Corp",
        ),
        Order(
            order_id="O-118",
            product="P-B",
            qty=20,
            due=datetime(2026, 10, 12, 15, 0),
            priority=2,
            customer="Global Industries",
        ),
    ]

    # P-A has step 1 on CNC-1 or CNC-2 (6 min/unit = 60m), step 2 on CNC-2 (3 min/unit = 30m)
    # P-B has step 1 on CNC-1 only (3 min/unit = 60m)
    routings = [
        RoutingStep(
            product="P-A",
            step=1,
            machines=["CNC-1", "CNC-2"],
            minutes_per_unit=6.0,
            skill_required="L1",
        ),
        RoutingStep(
            product="P-A",
            step=2,
            machines=["CNC-2"],
            minutes_per_unit=3.0,
            skill_required="L2",
        ),
        RoutingStep(
            product="P-B",
            step=1,
            machines=["CNC-1"],
            minutes_per_unit=3.0,
            skill_required="L1",
        ),
    ]

    # Changeover on CNC-1 from P-A to P-B takes 30 mins
    changeovers = [
        Changeover(from_product="P-A", to_product="P-B", minutes=30),
        Changeover(from_product="P-B", to_product="P-A", minutes=20),
    ]

    operators = [
        Operator(
            operator_id="OP-1",
            skill="L2",
            shift="A",
            shift_start=time(6, 0),
            shift_end=time(14, 0),
        ),
        Operator(
            operator_id="OP-2",
            skill="L3",
            shift="A",
            shift_start=time(6, 0),
            shift_end=time(14, 0),
        ),
    ]

    machines = ["CNC-1", "CNC-2"]
    plan_start = datetime(2026, 10, 12, 6, 0)

    return Problem(
        orders=orders,
        routings=routings,
        changeovers=changeovers,
        operators=operators,
        machines=machines,
        plan_start=plan_start,
    )


@pytest.fixture
def valid_jobs() -> list[Job]:
    """A valid schedule respecting all constraints."""
    return [
        # O-101 Step 1 on CNC-1: 06:00 to 07:00 (60 mins, P-A, OP-1)
        Job(
            order_id="O-101",
            step=1,
            product="P-A",
            machine="CNC-1",
            operator="OP-1",
            start=datetime(2026, 10, 12, 6, 0),
            end=datetime(2026, 10, 12, 7, 0),
        ),
        # Changeover gap on CNC-1: 07:00 to 07:30 (30 mins from P-A to P-B)
        # O-118 Step 1 on CNC-1: 07:30 to 08:30 (60 mins, P-B, OP-1)
        Job(
            order_id="O-118",
            step=1,
            product="P-B",
            machine="CNC-1",
            operator="OP-1",
            start=datetime(2026, 10, 12, 7, 30),
            end=datetime(2026, 10, 12, 8, 30),
        ),
        # O-101 Step 2 on CNC-2: 07:00 to 07:30 (30 mins, P-A, OP-2)
        Job(
            order_id="O-101",
            step=2,
            product="P-A",
            machine="CNC-2",
            operator="OP-2",
            start=datetime(2026, 10, 12, 7, 0),
            end=datetime(2026, 10, 12, 7, 30),
        ),
    ]


def test_valid_plan_passes(base_problem, valid_jobs):
    res = validate_plan(base_problem, valid_jobs)
    assert res.all_ok is True
    assert res.capacity_ok is True
    assert res.skill_ok is True
    assert res.changeover_ok is True
    assert res.precedence_ok is True
    assert res.eligibility_ok is True
    assert res.shift_ok is True
    assert res.wip_ok is True
    assert res.breakdown_ok is True
    assert len(res.violations) == 0


def test_capacity_violation_overlapping_jobs_on_same_machine(base_problem, valid_jobs):
    # Overlap two jobs on CNC-1: O-118 starts before O-101 finishes
    bad_jobs = [
        valid_jobs[0],  # 06:00 - 07:00 on CNC-1
        valid_jobs[1].model_copy(
            update={
                "start": datetime(2026, 10, 12, 6, 30),
                "end": datetime(2026, 10, 12, 7, 30),
            }
        ),
        valid_jobs[2],
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.capacity_ok is False
    assert res.all_ok is False
    assert any("Machine overlap" in v for v in res.violations)


def test_eligibility_annex_a_o118_unsupported_machine(base_problem, valid_jobs):
    # Annex A test case: O-118 is for P-B, which routing step only allows CNC-1.
    # Scheduling it on CNC-2 must fail eligibility.
    bad_jobs = [
        valid_jobs[0],
        valid_jobs[1].model_copy(update={"machine": "CNC-2"}),
        valid_jobs[2],
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.eligibility_ok is False
    assert res.all_ok is False
    assert any("Machine eligibility violation" in v for v in res.violations)


def test_eligibility_duration_mismatch(base_problem, valid_jobs):
    # O-101 step 1 expects 10 * 6 = 60 mins. If scheduled for only 45 mins, fails eligibility.
    bad_jobs = [
        valid_jobs[0].model_copy(
            update={"end": datetime(2026, 10, 12, 6, 45)}
        ),
        valid_jobs[1],
        valid_jobs[2],
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.eligibility_ok is False
    assert res.all_ok is False
    assert any("Duration violation" in v for v in res.violations)


def test_changeover_violation_insufficient_gap(base_problem, valid_jobs):
    # P-A to P-B on CNC-1 requires 30 mins gap.
    # Set gap to only 15 mins (07:00 to 07:15)
    bad_jobs = [
        valid_jobs[0],  # ends 07:00
        valid_jobs[1].model_copy(
            update={
                "start": datetime(2026, 10, 12, 7, 15),
                "end": datetime(2026, 10, 12, 8, 15),
            }
        ),
        valid_jobs[2],
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.changeover_ok is False
    assert res.all_ok is False
    assert any("Changeover violation" in v for v in res.violations)


def test_precedence_violation_step2_before_step1(base_problem, valid_jobs):
    # O-101 step 2 starts at 06:30, while step 1 ends at 07:00
    bad_jobs = [
        valid_jobs[0],  # 06:00 - 07:00
        valid_jobs[1],
        valid_jobs[2].model_copy(
            update={
                "start": datetime(2026, 10, 12, 6, 30),
                "end": datetime(2026, 10, 12, 7, 0),
            }
        ),
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.precedence_ok is False
    assert res.all_ok is False
    assert any("Precedence violation" in v for v in res.violations)


def test_precedence_missing_required_step(base_problem, valid_jobs):
    # O-101 step 2 is omitted entirely
    bad_jobs = [valid_jobs[0], valid_jobs[1]]
    res = validate_plan(base_problem, bad_jobs)
    assert res.precedence_ok is False
    assert res.all_ok is False
    assert any("Step coverage violation" in v for v in res.violations)


def test_skill_violation_insufficient_operator_skill(base_problem, valid_jobs):
    # P-A step 2 requires skill L2. Assign an operator with L1 (OP-3)
    prob_with_junior = base_problem.model_copy()
    junior_op = Operator(
        operator_id="OP-3",
        skill="L1",
        shift="A",
        shift_start=time(6, 0),
        shift_end=time(14, 0),
    )
    prob_with_junior.operators = list(base_problem.operators) + [junior_op]

    bad_jobs = [
        valid_jobs[0],
        valid_jobs[1],
        valid_jobs[2].model_copy(update={"operator": "OP-3"}),
    ]
    res = validate_plan(prob_with_junior, bad_jobs)
    assert res.skill_ok is False
    assert res.all_ok is False
    assert any("Skill violation" in v for v in res.violations)


def test_shift_violation_exceeds_max_overtime(base_problem, valid_jobs):
    # OP-1 shift ends at 14:00. Max overtime is 2h (16:00).
    # Job ending at 16:30 violates shift/overtime rule.
    bad_jobs = [
        valid_jobs[0].model_copy(
            update={
                "start": datetime(2026, 10, 12, 15, 30),
                "end": datetime(2026, 10, 12, 16, 30),
            }
        ),
        valid_jobs[1].model_copy(
            update={
                "start": datetime(2026, 10, 12, 17, 0),
                "end": datetime(2026, 10, 12, 18, 0),
            }
        ),
        valid_jobs[2],
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.shift_ok is False
    assert res.all_ok is False
    assert any("Overtime violation" in v for v in res.violations)


def test_shift_violation_operator_overlap(base_problem, valid_jobs):
    # OP-1 is assigned to two overlapping jobs at the same time
    bad_jobs = [
        valid_jobs[0],  # OP-1 on CNC-1 from 06:00 to 07:00
        valid_jobs[1],
        valid_jobs[2].model_copy(
            update={
                "operator": "OP-1",
                "start": datetime(2026, 10, 12, 6, 30),
                "end": datetime(2026, 10, 12, 7, 0),
            }
        ),
    ]
    res = validate_plan(base_problem, bad_jobs)
    assert res.shift_ok is False
    assert res.all_ok is False
    assert any("Operator overlap" in v for v in res.violations)


def test_breakdown_violation_job_overlaps_blocked_window(base_problem, valid_jobs):
    # CNC-1 is blocked 06:30 to 08:00
    blocked = [
        Blocked(
            machine="CNC-1",
            start=datetime(2026, 10, 12, 6, 30),
            end=datetime(2026, 10, 12, 8, 0),
        )
    ]
    res = validate_plan(base_problem, valid_jobs, blocked=blocked)
    assert res.breakdown_ok is False
    assert res.all_ok is False
    assert any("Breakdown violation on machine CNC-1" in v for v in res.violations)


def test_wip_violation_fixed_job_modified(base_problem, valid_jobs):
    # O-101 step 1 is marked fixed at 06:00 to 07:00 on CNC-1 with OP-1.
    fixed = [valid_jobs[0]]

    # If plan altered the machine to CNC-2
    altered_jobs = [
        valid_jobs[0].model_copy(update={"machine": "CNC-2"}),
        valid_jobs[1],
        valid_jobs[2],
    ]
    res = validate_plan(base_problem, altered_jobs, fixed_jobs=fixed)
    assert res.wip_ok is False
    assert res.all_ok is False
    assert any("Fixed job violation" in v for v in res.violations)


def test_compute_kpis_accurate(base_problem, valid_jobs):
    # In valid_jobs:
    # O-101 ends at 07:30 (due is 12:00) -> on time
    # O-118 ends at 08:30 (due is 15:00) -> on time
    # Overtime: both jobs end before OP shift end 14:00 -> 0 overtime
    # Changeover: P-A to P-B on CNC-1 -> 1 changeover
    kpis = compute_kpis(base_problem, valid_jobs)
    assert kpis.late_orders == 0
    assert kpis.total_lateness_h == 0.0
    assert kpis.overtime_h == 0.0
    assert kpis.changeovers == 1
    assert kpis.moved_jobs == 0

    # Now simulate a late order with overtime and compare against old_plan
    late_jobs = [
        # O-101 step 1 finishes at 07:00
        valid_jobs[0],
        # O-118 finishes at 16:00 (due was 15:00 -> 1.0 hr late)
        # OP-1 shift ends at 14:00 -> job worked 15:00 to 16:00 = 1.0 hr overtime
        valid_jobs[1].model_copy(
            update={
                "start": datetime(2026, 10, 12, 15, 0),
                "end": datetime(2026, 10, 12, 16, 0),
            }
        ),
        # O-101 step 2
        valid_jobs[2],
    ]

    kpis_late = compute_kpis(base_problem, late_jobs, old_plan=valid_jobs)
    assert kpis_late.late_orders == 1
    assert kpis_late.total_lateness_h == 1.0
    assert kpis_late.overtime_h == 1.0
    assert kpis_late.changeovers == 1
    # Only O-118 step 1 changed start time
    assert kpis_late.moved_jobs == 1
