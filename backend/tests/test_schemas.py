from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import Change, CheckResult, Job, Order, skill_rank


def test_job_times_serialize_in_contract_format():
    job = Job(order_id="O-1", step=1, product="P1", machine="CNC-1", operator="OP-1",
              start=datetime(2026, 10, 12, 6, 0), end=datetime(2026, 10, 12, 7, 30))
    assert job.model_dump()["start"] == "2026-10-12 06:00"


def test_change_uses_from_key_in_json():
    change = Change(order_id="O-1", step=1, from_="CNC-3 10:00", to="CNC-5 14:30",
                    reason_code="machine_down")
    assert change.model_dump()["from"] == "CNC-3 10:00"


def test_check_result_all_ok_false_if_any_rule_fails():
    flags = {name: True for name in ["capacity_ok", "skill_ok", "changeover_ok", "precedence_ok",
                                     "eligibility_ok", "shift_ok", "wip_ok", "breakdown_ok"]}
    assert CheckResult(**flags).all_ok
    assert not CheckResult(**{**flags, "skill_ok": False}).all_ok


def test_order_rejects_bad_values():
    with pytest.raises(ValidationError):
        Order(order_id="O-1", product="P1", qty=0, due=datetime(2026, 10, 12), priority=5, customer="C")


def test_skill_rank():
    assert skill_rank("L3") > skill_rank("l1")
