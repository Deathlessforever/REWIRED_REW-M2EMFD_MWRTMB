import json
from pathlib import Path

from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_reminders_button_calls_foreman_endpoint(page, base_url):
    fixture = json.loads((ROOT / "data" / "fixtures" / "state_foreman.json").read_text(encoding="utf-8"))
    requests = []

    def state(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(fixture))

    def reminders(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body='{"sent":3}')

    page.route("**/state?role=foreman", state)
    page.route("**/reminders/send", reminders)
    page.goto(f"{base_url}/dashboard/")
    button = page.get_by_role("button", name="Send reminders now")
    expect(button).to_be_visible()
    button.click()
    expect(page.locator("#state-status")).to_contain_text("Reminders recorded")
    assert requests == [{"actor": "foreman"}]
