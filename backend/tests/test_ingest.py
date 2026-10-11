from fastapi.testclient import TestClient

from app import store
from app.main import app

client = TestClient(app)

ORDERS = ("order_id,product,qty,due,priority,customer\n"
          "O-1,P1,10,2026-10-13 10:00,1,Cust A\n"
          "O-2,P1,-5,2026-10-13 10:00,1,Cust A\n")


def post(files_csv: str, **form):
    return client.post("/ingest", files={"file": ("orders.csv", files_csv, "text/csv")}, data=form)


def test_ingest_loads_good_rows_and_counts_bad_ones(tmp_db):
    response = post(ORDERS, meta='{"table": "orders"}')
    assert response.status_code == 200
    body = response.json()
    assert (body["rows_loaded"], body["rows_rejected"], body["status"]) == (1, 1, "partial")
    assert list(store.read_table("orders")["order_id"]) == ["O-1"]


def test_ingest_accepts_plain_table_field(tmp_db):
    assert post(ORDERS, table="orders").json()["rows_loaded"] == 1


def test_ingest_unknown_table_is_400(tmp_db):
    assert post(ORDERS, meta='{"table": "machines"}').status_code == 400
    assert post(ORDERS, meta="not json").status_code == 400
    assert post(ORDERS).status_code == 400


def test_ingest_missing_column_reports_failed(tmp_db):
    body = post("order_id,product\nO-1,P1\n", meta='{"table": "orders"}').json()
    assert body["status"] == "failed"
    assert "missing required column" in body["errors"][0]
