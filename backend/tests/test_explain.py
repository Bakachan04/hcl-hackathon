from unittest.mock import patch
import pytest

from app.explain import check_facts, explain


@pytest.fixture
def sample_facts():
    return {
        "kpis": {
            "late_orders": 0,
            "total_lateness_h": 0.0,
            "overtime_h": 1.5,
            "changeovers": 2,
            "moved_jobs": 1,
        },
        "changes": [
            {
                "order_id": "O-101",
                "step": 1,
                "from": "CNC-1",
                "to": "CNC-2",
                "reason_code": "machine_down",
            }
        ],
        "check": {
            "all_ok": True,
            "violations": [],
        },
        "weights": {
            "late": 10.0,
            "overtime": 3.0,
            "changeover": 1.0,
        },
        "disruption": {
            "kind": "breakdown",
            "target": "CNC-1",
            "at": "2026-10-12 08:00",
        },
    }


def test_faithful_text_passes_fact_check(sample_facts):
    text = (
        "Order O-101 step 1 was moved from CNC-1 to CNC-2 due to machine_down. "
        "The updated schedule results in 0 late orders and 1.5 hours of overtime. "
        "There are 2 changeovers across all machines and 1 moved job."
    )
    res = check_facts(text, sample_facts)
    assert res["ok"] is True
    assert len(res["unknown_items"]) == 0


def test_invented_order_id_fails(sample_facts):
    text = "Order O-999 was moved to CNC-2 to avoid disruption."
    res = check_facts(text, sample_facts)
    assert res["ok"] is False
    assert "O-999" in res["unknown_items"]


def test_invented_machine_id_fails(sample_facts):
    text = "Job for O-101 was rerouted to machine CNC-9."
    res = check_facts(text, sample_facts)
    assert res["ok"] is False
    assert "CNC-9" in res["unknown_items"]


def test_invented_operator_id_fails(sample_facts):
    text = "Operator OP-9 was assigned to step 1."
    res = check_facts(text, sample_facts)
    assert res["ok"] is False
    assert "OP-9" in res["unknown_items"]


def test_invented_clock_time_fails(sample_facts):
    text = "Order O-101 starts at 17:45 on CNC-2."
    res = check_facts(text, sample_facts)
    assert res["ok"] is False
    assert "17:45" in res["unknown_items"]


def test_invented_number_fails(sample_facts):
    text = "Replanning saved 500 dollars with 85 percent efficiency."
    res = check_facts(text, sample_facts)
    assert res["ok"] is False
    assert any(item in ["500", "85"] for item in res["unknown_items"])


def test_explain_with_faithful_llm_response(sample_facts):
    faithful_reply = (
        "Order O-101 was reassigned from CNC-1 to CNC-2 because of machine_down. "
        "The replanned schedule has 0 late orders and 1.5 hours of overtime. "
        "There are 2 changeovers and all constraints are satisfied."
    )
    with patch(
        "app.llm.complete",
        return_value=(faithful_reply, {"llm_calls": 1, "tokens": 30}),
    ):
        text, meta = explain(sample_facts)
        assert text == faithful_reply
        assert meta["fact_check_passed"] is True


def test_explain_with_hallucination_triggers_retry_and_fallback(sample_facts):
    hallucinated_reply = (
        "Order O-777 was reassigned to CNC-8 saving 999 dollars at 15:30."
    )
    with patch(
        "app.llm.complete",
        return_value=(hallucinated_reply, {"llm_calls": 1, "tokens": 20}),
    ):
        text, meta = explain(sample_facts)
        # Should fallback to deterministic explanation based only on facts
        assert meta["fact_check_passed"] is False
        assert meta["fallback"] is True
        assert "O-101" in text
        assert "O-777" not in text
        # Verify deterministic fallback itself passes fact checking!
        fallback_check = check_facts(text, sample_facts)
        assert fallback_check["ok"] is True

