from pathlib import Path

import pytest

from app import loader, store, validation
from scripts.generate_data import generate

ORDERS_HEADER = "order_id,product,qty,due,priority,customer\n"
ROUTINGS = ("product,step,machine_group,minutes_per_unit,skill_required\n"
            "P1,1,CNC-1|CNC-2,1.5,L1\nP1,2,LTH-1,1.0,L2\nP2,1,CNC-2,2.0,L1\n")
CS = ("from_product,to_product,minutes,operator_id,skill,shift\n"
      "P1,P2,20,,,\nP2,P1,45,,,\n,,,OP-01,L2,A\n,,,OP-02,L1,B\n")


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_required_column_fails_whole_file(tmp_db, tmp_path):
    path = write(tmp_path, "orders.csv", "order_id,product,qty,due,priority\nO-1,P1,10,2026-10-13 10:00,1\n")
    result = loader.load_table("orders", path)
    assert result.status == "failed"
    assert result.rows_loaded == 0
    assert "customer" in result.errors[0]
    assert store.read_table("orders").empty


def test_bad_rows_are_rejected_with_reasons_and_good_rows_kept(tmp_db, tmp_path):
    path = write(tmp_path, "orders.csv", ORDERS_HEADER
                 + "O-1,P1,10,2026-10-13 10:00,1,Cust A\n"
                 + "O-2,P1,0,2026-10-13 10:00,1,Cust A\n"         # qty must be > 0
                 + "O-3,P1,10,not-a-date,1,Cust A\n"              # bad datetime
                 + "O-4,P2,10,2026-10-13 10:00,9,Cust B\n")       # priority 1..3
    result = loader.load_table("orders", path)
    assert (result.status, result.rows_loaded, result.rows_rejected) == ("partial", 1, 3)
    assert [e.split(":")[0] for e in result.errors] == ["line 3", "line 4", "line 5"]
    assert list(store.read_table("orders")["order_id"]) == ["O-1"]


def test_duplicate_key_keeps_first_row(tmp_db, tmp_path):
    path = write(tmp_path, "orders.csv", ORDERS_HEADER
                 + "O-1,P1,10,2026-10-13 10:00,1,Cust A\n"
                 + "O-1,P2,99,2026-10-14 10:00,2,Cust B\n")
    result = loader.load_table("orders", path)
    assert (result.rows_loaded, result.rows_rejected) == (1, 1)
    assert "duplicate O-1" in result.errors[0]
    assert store.read_table("orders").iloc[0]["qty"] == "10"


def test_annex_b_columns_only_build_a_problem(tmp_db, tmp_path):
    write(tmp_path, "orders.csv", ORDERS_HEADER + "O-1,P1,10,2026-10-13 10:00,1,Cust A\n"
          + "O-2,P2,5,2026-10-13T12:00:00,3,Cust B\n")
    write(tmp_path, "routings_machines.csv", ROUTINGS)
    write(tmp_path, "changeovers_skills.csv", CS)
    results = loader.load_folder(tmp_path)
    assert all(r.status == "ok" for r in results.values())

    problem = loader.load_problem()
    assert problem.machines == ["CNC-1", "CNC-2", "LTH-1"]
    assert problem.routings[0].machines == ["CNC-1", "CNC-2"]
    assert problem.orders[0].movable and problem.orders[0].wip_step is None
    assert {op.operator_id: op.shift_start.hour for op in problem.operators} == {"OP-01": 6, "OP-02": 14}
    assert len(problem.changeovers) == 2
    assert validation.all_passed(validation.run_checks(problem))


def test_unknown_shift_and_mixed_row_rejected(tmp_db, tmp_path):
    path = write(tmp_path, "cs.csv", CS + ",,,OP-03,L1,Z\nP1,P2,10,OP-04,L1,A\n")
    result = loader.load_table("changeovers_skills", path)
    assert result.rows_rejected == 2
    assert "unknown shift" in result.errors[0]
    assert "mixes" in result.errors[1]


def test_unknown_table_raises():
    with pytest.raises(ValueError):
        loader.check_table("machines", b"a,b\n1,2\n")


def test_validation_flags_missing_routing_and_changeover(tmp_db, tmp_path):
    write(tmp_path, "orders.csv", ORDERS_HEADER + "O-1,P1,10,2026-10-13 10:00,1,A\n"
          + "O-2,P3,10,2026-10-11 10:00,1,A\n")  # P3 unrouted, due before plan start
    write(tmp_path, "routings_machines.csv", ROUTINGS)
    write(tmp_path, "changeovers_skills.csv", CS)
    loader.load_folder(tmp_path)
    results = {r["check"]: r for r in validation.run_checks(loader.load_problem(), {"orders": 3})}
    assert not results["order_products_have_routing"]["passed"]
    assert not results["due_after_plan_start"]["passed"]
    assert "P1->P3" in results["changeovers_cover_product_pairs"]["detail"]
    assert not results["row_counts_match_data_card"]["passed"]


def test_generated_pack_is_deterministic_and_valid(tmp_db, tmp_path):
    generate(42, tmp_path / "a")
    generate(42, tmp_path / "b")
    for f in (tmp_path / "a").iterdir():
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes()

    results = loader.load_folder(tmp_path / "a")
    assert all(r.status == "ok" for r in results.values())
    problem = loader.load_problem()
    assert len(problem.orders) >= 40 and len(problem.machines) >= 6
    assert validation.all_passed(validation.run_checks(problem))
    kinds = {d.kind for d in loader.load_disruptions()}
    assert kinds == {"breakdown", "rush_order"}
