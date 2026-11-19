from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_frontend_and_demo_evidence_are_served():
    for path, title in [("/chat/", "ChitMirror Chat"), ("/dashboard/", "ChitMirror Dashboard")]:
        response = client.get(path)
        assert response.status_code == 200
        assert title in response.text
        for asset in ["config.js", "app.js", "style.css"]:
            assert client.get(path + asset).status_code == 200

    assert client.get("/data/dashboard.json").status_code == 200
    assert client.get("/data/bank.csv").text.startswith("utr,amount,date,receiver,memberId,memberName")
    assert client.get("/data/scenarios.json").status_code == 200
    assert client.get("/data/screenshot_manifest.json").status_code == 200


def test_only_matching_bank_evidence_enters_the_ledger():
    client.post("/api/reset")
    scenarios = client.get("/data/scenarios.json").json()["scenarios"]
    expected = {
        "genuine": "verified",
        "duplicate": "duplicate",
        "fake": "failed",
        "amount": "mismatch",
        "receiver": "mismatch",
    }

    for name, status in expected.items():
        scenario = scenarios[name]
        response = client.post(
            "/api/verify",
            json={
                "fields": {
                    "utr": scenario["utr"],
                    "amount": scenario["amount"],
                    "date": scenario["date"],
                    "receiver": scenario["receiver"],
                    "memberId": scenario["member"],
                }
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["status"] == status

    state = client.get("/api/state").json()["state"]
    assert len(state["payments"]) == 14
    assert state["payments"][-1]["utr"] == scenarios["genuine"]["utr"]
    assert [event["status"] for event in state["audit"][:5]] == list(reversed(expected.values()))
    client.post("/api/reset")

