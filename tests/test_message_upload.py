from fastapi.testclient import TestClient

from backend.main import app
from backend.screenshot_reader import ScreenshotClaim


def test_uploaded_fake_utr_is_flagged_and_audited(tmp_path, monkeypatch):
    database = tmp_path / "messages.db"
    monkeypatch.setenv("CHITMIRROR_DATABASE", str(database))
    monkeypatch.setattr(
        "backend.main.read_uploaded_screenshot",
        lambda *_args: ScreenshotClaim("845270319999", 500000, "saanvi-circle@demo.invalid", "SUCCESS", "2026-11-04", None, "UPI", None),
    )
    client = TestClient(app)
    assert client.post("/demo/load", json={"actor": "foreman"}).status_code == 200
    response = client.post(
        "/message", data={"sender": "member-20", "text": ""},
        files={"image": ("fake.png", b"synthetic image bytes", "image/png")},
    )
    assert response.status_code == 200
    result = response.json()["bubbles"][-1]
    assert result["type"] == "result_card"
    assert result["status"] == "needs_review"
    state = client.get("/state", params={"role": "foreman"}).json()
    assert any(flag["member_id"] == "member-20" and flag["month"] == 4 for flag in state["flags"])
    assert any("bank" in item["reason"].lower() for item in state["audit_log"])
