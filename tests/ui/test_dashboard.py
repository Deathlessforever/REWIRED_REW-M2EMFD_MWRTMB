from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[2]
STATE_FIXTURE = ROOT / "data" / "fixtures" / "state_foreman.json"
FOREMAN_ROUTE = re.compile(r".*/state\?role=foreman$")
MEMBER_ROUTE = re.compile(r".*/state\?role=member&member_id=.+$")


def fixture_state():
    return json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))


def member_state():
    state = copy.deepcopy(fixture_state())
    state["flags"] = []
    state["overdue"] = []
    state["audit_log"] = []
    state["private_bubbles"] = [{"type": "reminder", "text": "Submit month 5 proof by Friday."}]
    return state


def empty_state():
    return {
        "members": [],
        "months": [],
        "ledger": [],
        "counters": {"collected_paise": 0, "paid": 0, "total_members": 0, "needs_review": 0, "overdue": 0},
        "flags": [],
        "overdue": [],
        "audit_log": [],
        "statement": [],
        "private_bubbles": [],
    }


def fulfill_state(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def open_dashboard(page, base_url):
    page.goto(f"{base_url}/dashboard/")


def test_dashboard_binds_kpis_from_shared_state(page, base_url):
    page.route(FOREMAN_ROUTE, lambda route: fulfill_state(route, fixture_state()))
    open_dashboard(page, base_url)

    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹3,29,350.00")
    expect(page.get_by_test_id("kpi-paid")).to_have_text("73 / 20")
    expect(page.get_by_test_id("kpi-review")).to_have_text("2")
    expect(page.get_by_test_id("kpi-overdue")).to_have_text("2")
    expect(page.get_by_role("button", name="Foreman")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-role-panel='foreman']").first).to_be_visible()
    expect(page.locator("[data-role-panel='member']")).to_be_hidden()


def test_role_toggle_switches_visible_sections(page, base_url):
    page.route(FOREMAN_ROUTE, lambda route: fulfill_state(route, fixture_state()))
    page.route(MEMBER_ROUTE, lambda route: fulfill_state(route, member_state()))
    open_dashboard(page, base_url)

    page.get_by_role("button", name="Member").click()
    expect(page.get_by_role("button", name="Member")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-role-panel='member']")).to_be_visible()
    expect(page.locator("[data-role-panel='foreman']").first).to_be_hidden()
    expect(page.locator("#member-select")).to_be_visible()

    page.get_by_role("button", name="Foreman").click()
    expect(page.get_by_role("button", name="Foreman")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-role-panel='foreman']").first).to_be_visible()
    expect(page.locator("[data-role-panel='member']")).to_be_hidden()


def test_member_view_uses_member_endpoint_without_foreman_details(page, base_url):
    seen = []
    page.route(FOREMAN_ROUTE, lambda route: fulfill_state(route, fixture_state()))

    def member_stub(route):
        seen.append(route.request.url)
        fulfill_state(route, member_state())

    page.route(MEMBER_ROUTE, member_stub)
    open_dashboard(page, base_url)
    page.get_by_role("button", name="Member").click()

    expect(page.locator("#member-bubbles")).to_contain_text("Submit month 5 proof by Friday.")
    expect(page.locator("#review-list")).to_be_hidden()
    expect(page.locator("#audit-list")).to_be_hidden()
    page.wait_for_function("() => window.chitmirrorDashboard.role === 'member'")
    assert page.evaluate("() => window.chitmirrorDashboard.role") == "member"
    assert any("member_id=member-07" in url for url in seen)


def test_live_state_updates_kpis(page, base_url):
    initial = fixture_state()
    changed = copy.deepcopy(initial)
    changed["counters"]["collected_paise"] += 100
    changed["counters"]["paid"] += 1
    changed["counters"]["needs_review"] -= 1
    calls = 0

    def state_stub(route):
        nonlocal calls
        calls += 1
        fulfill_state(route, initial if calls == 1 else changed)

    page.route(FOREMAN_ROUTE, state_stub)
    open_dashboard(page, base_url)
    expect(page.get_by_test_id("kpi-review")).to_have_text("2")

    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹3,29,351.00", timeout=3500)
    expect(page.get_by_test_id("kpi-paid")).to_have_text("74 / 20")
    expect(page.get_by_test_id("kpi-review")).to_have_text("1")
    assert calls >= 2


def test_empty_state_is_safe(page, base_url):
    page.route(FOREMAN_ROUTE, lambda route: fulfill_state(route, empty_state()))
    open_dashboard(page, base_url)

    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹0.00")
    expect(page.get_by_test_id("kpi-paid")).to_have_text("0 / 0")
    expect(page.get_by_test_id("kpi-review")).to_have_text("0")
    expect(page.get_by_test_id("kpi-overdue")).to_have_text("0")
    expect(page.locator("#review-list")).to_contain_text("No items need review.")
    expect(page.locator("#ledger-grid")).to_contain_text("Member")


def test_api_failure_preserves_last_state_and_shows_indicator(page, base_url):
    calls = 0

    def state_stub(route):
        nonlocal calls
        calls += 1
        if calls == 1:
            fulfill_state(route, fixture_state())
        else:
            route.abort()

    page.route(FOREMAN_ROUTE, state_stub)
    open_dashboard(page, base_url)
    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹3,29,350.00")

    status = page.locator("#state-status")
    expect(status).to_contain_text("fixture", timeout=3500)
    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹3,29,350.00")
    expect(page.locator("#ledger-error")).to_be_visible()
    assert calls >= 2


def test_polling_does_not_duplicate_or_continue_after_stop(page, base_url):
    page.route(FOREMAN_ROUTE, lambda route: fulfill_state(route, fixture_state()))
    open_dashboard(page, base_url)
    expect(page.get_by_test_id("kpi-collected")).to_have_text("₹3,29,350.00")
    initial = page.evaluate("() => window.chitmirrorDashboard.requestCount")

    time.sleep(3.4)
    during = page.evaluate("() => window.chitmirrorDashboard.requestCount")
    assert 1 <= during - initial <= 3

    page.evaluate("() => window.chitmirrorDashboard.stop()")
    stopped = page.evaluate("() => window.chitmirrorDashboard.requestCount")
    time.sleep(1.8)
    assert page.evaluate("() => window.chitmirrorDashboard.requestCount") == stopped


def test_role_toggle_works_on_mobile(page, base_url):
    page.set_viewport_size({"width": 390, "height": 844})
    page.route(FOREMAN_ROUTE, lambda route: fulfill_state(route, fixture_state()))
    page.route(MEMBER_ROUTE, lambda route: fulfill_state(route, member_state()))
    open_dashboard(page, base_url)

    expect(page.locator(".role-toggle")).to_be_visible()
    page.get_by_role("button", name="Member").click()
    expect(page.locator("[data-role-panel='member']")).to_be_visible()
    expect(page.get_by_test_id("kpi-collected")).to_be_visible()
