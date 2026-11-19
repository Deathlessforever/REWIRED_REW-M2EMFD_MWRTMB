from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database import audited_transaction, connect
from backend.main import app
from test_contract import validator_for


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "messages.db"
    db, context = connect(path)
    with audited_transaction(db, context, actor="foreman", reason="demo setup"):
        db.executemany("INSERT INTO members VALUES (?, ?)", [("m1", "Paid Member"), ("m2", "Unpaid Member")])
        db.execute("INSERT INTO months VALUES (1, '2099-01-05')")
        db.execute("INSERT INTO months VALUES (2, '2099-02-05')")
        db.execute("INSERT INTO payments VALUES ('p2', 'm2', 2, 455000, NULL, 'pending')")
        db.execute("INSERT INTO ledger_entries VALUES ('e1', 'm2', 1, NULL, 465000, 'payment')")
        db.execute("INSERT INTO ledger_entries VALUES ('e2', 'm2', 2, NULL, 455000, 'payment')")
        db.execute("INSERT INTO reminders VALUES ('r1', 'm1', 2, 'overdue', '2099-02-06', 'Private reminder for Paid Member.')")
        db.execute("INSERT INTO reminders VALUES ('r2', 'm2', 2, 'overdue', '2099-02-06', 'Private reminder for Unpaid Member.')")
    monkeypatch.setenv("CHITMIRROR_DATABASE", str(path))
    yield path
    db.close()


def post_message(path, sender, text):
    client = TestClient(app)
    return client.post("/message", json={"sender": sender, "text": text})


def test_dues_reply_uses_sender_and_shared_state(store):
    validator_for("message_request").validate({"sender": "m2", "text": "dues"})
    response = post_message(store, "m2", "What are my dues?")
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    reply = response.json()["bubbles"][0]["text"]
    assert "Unpaid Member" in reply
    assert "month 2" in reply
    assert "2099-02-05" in reply
    assert "₹4,550.00" in reply
    assert "Paid Member" not in reply


def test_statement_reply_is_chronological_and_has_empty_state(store):
    response = post_message(store, "m2", "statement")
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    reply = response.json()["bubbles"][0]["text"]
    assert reply.index("Month 1") < reply.index("Month 2")
    assert "₹4,650.00" in reply
    assert "₹4,550.00" in reply
    assert "dates, descriptions and running balances are not provided" in reply

    empty = post_message(store, "m1", "statement")
    assert empty.status_code == 200
    assert "No statement entries are available for Paid Member." in empty.json()["bubbles"][0]["text"]


def test_private_reminders_are_only_returned_to_their_member(store):
    response = post_message(store, "m2", "reminders")
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    texts = [bubble["text"] for bubble in response.json()["bubbles"]]
    assert any("Private reminder for Unpaid Member." in text for text in texts)
    assert not any("Private reminder for Paid Member." in text for text in texts)
    assert any(bubble["type"] == "reminder" for bubble in response.json()["bubbles"])


def test_invalid_message_requests_return_error_contract(store):
    unknown = post_message(store, "not-a-member", "dues")
    assert unknown.status_code == 422
    validator_for("error_response").validate(unknown.json())

    blank = post_message(store, "m2", "   ")
    assert blank.status_code == 422
    validator_for("error_response").validate(blank.json())

    target = TestClient(app).post("/message", json={"sender": "m2", "text": "dues", "member_id": "m1"})
    assert target.status_code == 422
    validator_for("error_response").validate(target.json())


def test_foreman_reply_uses_shared_contract(store):
    response = post_message(store, "foreman", "status")
    assert response.status_code == 200
    validator_for("message_response").validate(response.json())
    assert response.json()["bubbles"][0]["type"] == "text"
