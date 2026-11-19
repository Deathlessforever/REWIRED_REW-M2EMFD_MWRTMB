import json
import re
from pathlib import Path

from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[2]
STATE_FIXTURE = ROOT / "data" / "fixtures" / "state_foreman.json"


EMPTY_STATE = {
    "members": [],
    "months": [],
    "ledger": [],
    "counters": {
        "collected_paise": 0,
        "paid": 0,
        "total_members": 0,
        "needs_review": 0,
        "overdue": 0,
    },
    "flags": [],
    "overdue": [],
    "audit_log": [],
    "statement": [],
    "private_bubbles": [],
}


def fulfill(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def test_dashboard_load_demo_button_posts_and_refreshes_state(page, base_url):
    fixture = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))
    loaded = False
    requests = []

    def state_stub(route):
        fulfill(route, fixture if loaded else EMPTY_STATE)

    def load_stub(route):
        nonlocal loaded
        requests.append(route.request.post_data_json)
        loaded = True
        fulfill(route, {"loaded": True})

    page.route(re.compile(r".*/state\?role=foreman$"), state_stub)
    page.route(re.compile(r".*/demo/load$"), load_stub)
    page.goto(f"{base_url}/dashboard/")

    button = page.get_by_role("button", name="Load four-month demo")
    expect(button).to_be_visible()
    button.click()

    expect(page.locator("#state-status")).to_contain_text("Demo loaded")
    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹3,29,350.00", timeout=4000)
    expect(page.locator("#ledger-grid tbody tr")).to_have_count(20)
    assert requests == [{"actor": "foreman"}]
