import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.database import audited_transaction, connect
from backend.demo import load_demo, run_planted_scenarios
from backend.main import app
from test_contract import validator_for


ROOT = Path(__file__).resolve().parents[1]


def test_all_planted_scenarios_match_expected_results():
    results = run_planted_scenarios()
    assert {item["id"] for item in results} == {
        "genuine_on_time", "reused_utr", "fake_utr_not_in_csv", "wrong_amount", "late_payer"
    }
    assert {item["result"]["bubble"]["status"] for item in results} == {
        "verified", "duplicate", "needs_review", "wrong_amount"
    }


def test_demo_load_endpoint_seeds_four_months_and_is_idempotent(tmp_path, monkeypatch):
    database = tmp_path / "demo.db"
    monkeypatch.setenv("CHITMIRROR_DATABASE", str(database))
    client = TestClient(app)

    response = client.post("/demo/load", json={"actor": "foreman"})
    assert response.status_code == 200
    validator_for("demo_load_response").validate(response.json())
    assert response.json() == {"loaded": True}

    state_response = client.get("/state", params={"role": "foreman"})
    assert state_response.status_code == 200
    state = state_response.json()
    validator_for("state_response").validate(state)
    assert len(state["members"]) == 20
    assert state["months"] == [1, 2, 3, 4]
    assert len(state["ledger"]) == 80
    assert sum(entry["status"] == "verified" for entry in state["ledger"]) == 73
    assert len(state["flags"]) == 2

    db, _ = connect(database)
    try:
        before = {
            "members": db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
            "payments": db.execute("SELECT COUNT(*) FROM payments").fetchone()[0],
            "posted": db.execute("SELECT COUNT(*) FROM ledger_entries WHERE kind='payment'").fetchone()[0],
            "evidence": db.execute("SELECT COUNT(*) FROM bank_evidence").fetchone()[0],
            "audit": db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
        }
        assert {key: before[key] for key in ("members", "payments", "posted", "evidence")} == {
            "members": 20, "payments": 77, "posted": 73, "evidence": 73
        }
        assert before["audit"] > 73
    finally:
        db.close()

    repeated = client.post("/demo/load", json={"actor": "foreman"})
    assert repeated.status_code == 200
    db, _ = connect(database)
    try:
        after = {
            "members": db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
            "payments": db.execute("SELECT COUNT(*) FROM payments").fetchone()[0],
            "posted": db.execute("SELECT COUNT(*) FROM ledger_entries WHERE kind='payment'").fetchone()[0],
            "evidence": db.execute("SELECT COUNT(*) FROM bank_evidence").fetchone()[0],
            "audit": db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
        }
        assert after == before
    finally:
        db.close()


def test_demo_load_rejects_non_foreman_and_nonempty_database(tmp_path, monkeypatch):
    client = TestClient(app)
    database = tmp_path / "occupied.db"
    db, context = connect(database)
    with audited_transaction(db, context, actor="foreman", reason="existing demo record"):
        db.execute("INSERT INTO members VALUES ('other', 'Existing member')")
    db.close()
    monkeypatch.setenv("CHITMIRROR_DATABASE", str(database))

    denied = client.post("/demo/load", json={"actor": "member-01"})
    assert denied.status_code == 422
    validator_for("error_response").validate(denied.json())

    conflict = client.post("/demo/load", json={"actor": "foreman"})
    assert conflict.status_code == 409
    validator_for("error_response").validate(conflict.json())
    assert conflict.json()["error"]["code"] == "demo_load_conflict"

    db, _ = connect(database)
    try:
        assert db.execute("SELECT name FROM members").fetchall() == [("Existing member",)]
        assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM bank_evidence").fetchone()[0] == 0
    finally:
        db.close()


def test_direct_demo_load_requires_foreman():
    db, context = connect(":memory:")
    try:
        with pytest.raises(ValueError, match="foreman"):
            load_demo(db, context, actor="member-01")
    finally:
        db.close()
