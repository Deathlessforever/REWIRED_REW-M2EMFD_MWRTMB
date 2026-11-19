from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_both_frontends_are_served():
    for path, title in [("/chat/", "ChitMirror Chat"), ("/dashboard/", "ChitMirror Dashboard")]:
        response = client.get(path)
        assert response.status_code == 200
        assert title in response.text
        assets = ["config.js", "app.js", "style.css"]
        if path == "/chat/":
            assets.extend(["api.js", "shell.css"])
        for asset in assets:
            assert client.get(path + asset).status_code == 200


def test_t06_demo_csv_scenarios_validate_against_contract():
    import json
    from pathlib import Path

    from scripts.validate_demo_data import validate_demo_data
    from test_contract import validator_for

    root = Path(__file__).resolve().parent.parent
    assert validate_demo_data() == []
    scenarios = json.loads((root / "data" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    for scenario in scenarios:
        validator_for("bubble").validate(scenario["expected_result"]["bubble"])

