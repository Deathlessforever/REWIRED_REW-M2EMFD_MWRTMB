import pytest
from fastapi.testclient import TestClient

from backend.stub import app
from test_contract import validator_for

client = TestClient(app)


def test_browser_cors_preflight():
    response = client.options("/message", headers={"Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"


def test_json_chat_commands_are_accepted_by_stub():
    response = client.post("/message", json={"sender": "member-07", "text": "statement"})
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    assert "Statement for Member 07" in response.json()["bubbles"][0]["text"]
    other = client.post("/message", json={"sender": "member-08", "text": "statement"})
    assert "Statement for Member 08" in other.json()["bubbles"][0]["text"]
    assert "Statement for Member 07" not in str(other.json())
    invalid = client.post("/message", json={"sender": "member-07", "text": "dues", "member_id": "member-08"})
    assert invalid.status_code == 422


@pytest.mark.parametrize("status", ["verified", "duplicate", "wrong_amount", "needs_review"])
def test_each_result_is_contract_valid(status):
    response = client.post("/message", data={"sender": "member-7", "text": f"stub:{status}"})
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    assert response.json()["bubbles"][0]["status"] == status


@pytest.mark.parametrize("kind", ["review_request", "reminder"])
def test_other_bubble_types(kind):
    response = client.post("/message", data={"sender": "foreman", "text": f"stub:{kind}"})
    validator_for("message_response").validate(response.json())
    assert response.json()["bubbles"][0]["type"] == kind


def test_image_upload_and_missing_input():
    response = client.post("/message", data={"sender": "member-7", "text": ""}, files={"image": ("test.png", b"sample", "image/png")})
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    response = client.post("/message", data={"sender": "member-7"})
    assert response.status_code == 422
    validator_for("error_response").validate(response.json())


def test_review_and_controls():
    payload = {"actor": "foreman", "item_id": "review-1", "decision": "approve", "reason": "checked"}
    response = client.post("/review", json=payload)
    validator_for("review_response").validate(response.json())
    response = client.post("/review", json={**payload, "reason": "  "})
    assert response.status_code == 422
    validator_for("error_response").validate(response.json())
    for path, schema in [("/reminders/send", "reminders_response"), ("/demo/load", "demo_load_response")]:
        response = client.post(path, json={"actor": "foreman"})
        assert response.status_code == 200
        validator_for(schema).validate(response.json())


def test_state_contract_and_private_filtering():
    for query in ["role=foreman", "role=member&member_id=member-07", "role=member&member_id=member-08"]:
        response = client.get("/state?" + query)
        assert response.status_code == 200
        validator_for("state_response").validate(response.json())
    foreman = client.get("/state?role=foreman").json()
    assert len(foreman["members"]) == 20
    assert foreman["months"] == [1, 2, 3, 4]
    assert len(foreman["ledger"]) == 80
    member = client.get("/state?role=member&member_id=member-08").json()
    assert not any(member[key] for key in ("flags", "audit_log", "private_bubbles"))
    assert len(member["statement"]) == 4
    assert client.get("/state?role=member&member_id=unknown").status_code == 422
