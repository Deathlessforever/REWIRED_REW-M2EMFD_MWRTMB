import copy
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"
STATE_FIXTURE = FIXTURES / "state_foreman.json"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fulfill(payload):
    body = json.dumps(payload)
    return lambda route: route.fulfill(status=200, content_type="application/json", body=body)


def state_for(reminders=None):
    state = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))
    state["private_bubbles"] = copy.deepcopy(reminders or [])
    return state


def route_chat(page, messages, *, member_reminders=None):
    page.route(re.compile(r".*/state\?role=foreman$"), fulfill(state_for()))
    reminders = member_reminders or {}

    def serve_member_state(route):
        member_id = parse_qs(urlparse(route.request.url).query).get("member_id", [""])[0]
        fulfill(state_for(reminders.get(member_id, [])))(route)

    page.route(re.compile(r".*/state\?role=member&member_id=.+$"), serve_member_state)
    page.route(re.compile(r".*/message$"), messages)


def test_smoke_statement_fixture_renders(page, base_url):
    sent = []
    reply = load_fixture("chat_statement_reply.json")

    def serve_message(route):
        sent.append(route.request.post_data_json)
        fulfill(reply)(route)

    route_chat(page, serve_message)
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Sending as").select_option("member-07")
    page.get_by_label("Message or foreman command").fill("statement")
    page.get_by_role("button", name="Send message").click()

    result = page.get_by_test_id("statement-result")
    expect(result).to_be_visible()
    expect(result).to_contain_text("Statement for Member 07")
    expect(result).to_contain_text("Month 1")
    expect(result).to_contain_text("dividend ₹350.00")
    assert sent == [{"sender": "member-07", "text": "statement"}]


def test_dues_command_shows_correct_dues(page, base_url):
    route_chat(page, fulfill(load_fixture("chat_dues_reply.json")))
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Sending as").select_option("member-07")
    page.get_by_label("Message or foreman command").fill("What are my dues?")
    page.get_by_role("button", name="Send message").click()

    result = page.get_by_test_id("dues-result")
    expect(result).to_contain_text("Dues for Member 07")
    expect(result).to_contain_text("2026-04-05")
    expect(result).to_contain_text("pending")
    expect(result).to_contain_text("₹4,350.00")


def test_reminder_fixture_renders_as_private_bubble(page, base_url):
    reminder = load_fixture("chat_reminder_reply.json")["bubbles"][1]
    route_chat(
        page,
        fulfill(load_fixture("chat_reminder_reply.json")),
        member_reminders={"member-07": [reminder]},
    )
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Sending as").select_option("member-07")
    expect(page.locator("#reminder-section")).to_be_visible()
    expect(page.locator("#reminder-feed [data-testid='reminder-bubble']")).to_contain_text(reminder["text"])

    page.get_by_label("Message or foreman command").fill("reminders")
    page.get_by_role("button", name="Send message").click()
    expect(page.locator("#message-list [data-testid='reminder-bubble']")).to_contain_text(reminder["text"])


def test_member_isolation_and_sender_switch_clears_stale_reminders(page, base_url):
    first = {"type": "reminder", "text": "Private only for Member 07."}
    second = {"type": "reminder", "text": "Private only for Member 08."}
    route_chat(
        page,
        fulfill({"bubbles": []}),
        member_reminders={"member-07": [first], "member-08": [second]},
    )
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Sending as").select_option("member-07")
    expect(page.locator("#reminder-feed")).to_contain_text(first["text"])
    expect(page.locator("#reminder-feed")).not_to_contain_text(second["text"])

    page.get_by_label("Sending as").select_option("member-08")
    expect(page.locator("#reminder-feed")).to_contain_text(second["text"])
    expect(page.locator("#reminder-feed")).not_to_contain_text(first["text"])

    page.get_by_label("Sending as").select_option("foreman")
    expect(page.locator("#reminder-section")).to_be_hidden()
    expect(page.locator("#reminder-feed")).to_be_empty()
    expect(page.locator("#review-queue")).to_be_visible()
    expect(page.locator("#message-list")).not_to_contain_text(second["text"])


def test_empty_and_error_states_are_visible(page, base_url):
    calls = []

    def serve_message(route):
        calls.append(route.request.post_data_json)
        if len(calls) == 1:
            fulfill({"bubbles": []})(route)
        else:
            route.abort()

    route_chat(page, serve_message)
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Sending as").select_option("member-07")
    page.get_by_label("Message or foreman command").fill("dues")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_test_id("empty-result")).to_contain_text("No details are available for this command.")

    page.get_by_label("Message or foreman command").fill("statement")
    page.get_by_role("button", name="Send message").click()
    expect(page.locator("#notice")).to_have_class("notice error")
    assert page.locator("#notice").inner_text().strip()
    assert len(calls) == 2


def test_reminder_empty_state_is_visible(page, base_url):
    route_chat(page, fulfill({"bubbles": []}), member_reminders={"member-07": []})
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Sending as").select_option("member-07")
    expect(page.locator("#reminder-status")).to_contain_text("No private reminders for this sender.")
