import json
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[2]
STATE_FIXTURE = ROOT / "data" / "fixtures" / "state_foreman.json"


def serve_json(payload, status=200):
    body = json.dumps(payload)
    return lambda route: route.fulfill(status=status, content_type="application/json", body=body)


def test_chat_sender_message_reply_result_and_timestamps(page, base_url):
    state = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))
    captured = []

    page.route("**/health", serve_json({"status": "ok"}))
    page.route(re.compile(r".*/state\?role=foreman$"), serve_json(state))

    def message_reply(route):
        captured.append({"content_type": route.request.headers.get("content-type", ""), "body": route.request.post_data or ""})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"bubbles": [
                {"type": "text", "text": "Payment received for checking."},
                {"type": "result_card", "status": "needs_review", "amount_paise": 445007, "utr": None, "reason": "Independent bank evidence is required."},
            ]}),
        )

    page.route(re.compile(r".*/message$"), message_reply)
    page.goto(f"{base_url}/chat/")

    expect(page.get_by_role("heading", name="ChitMirror Chat")).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="Backend connected")).to_be_visible()
    sender = page.get_by_label("Sending as")
    expect(sender.locator("option").first).to_have_text("Foreman")
    expect(sender.locator("option", has_text="Member 07")).to_have_count(1)
    sender.select_option("member-07")
    expect(sender).to_have_value("member-07")

    message = page.get_by_label("Message or foreman command")
    message.fill("I sent the March payment")
    message.press("Control+Enter")

    outgoing = page.locator(".member-bubble").filter(has_text="I sent the March payment")
    expect(outgoing).to_be_visible()
    expect(outgoing.locator(".bubble-label")).to_have_text("Member 07")
    expect(page.get_by_text("Payment received for checking.")).to_be_visible()
    result = page.locator(".result-bubble")
    expect(result).to_contain_text("needs_review")
    expect(result).to_contain_text("Independent bank evidence is required.")
    timestamps = page.locator("#message-list .bubble time")
    expect(timestamps).to_have_count(4)
    for timestamp in timestamps.all():
        datetime.fromisoformat(timestamp.get_attribute("datetime").replace("Z", "+00:00"))

    assert len(captured) == 1
    assert captured[0]["content_type"].startswith("multipart/form-data; boundary=")
    assert re.search(r'name="sender"\r\n\r\nmember-07\r\n', captured[0]["body"])
    assert re.search(r'name="text"\r\n\r\nI sent the March payment\r\n', captured[0]["body"])


def test_chat_api_validation_error_is_visible_and_recoverable(page, base_url):
    state = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))
    page.route("**/health", serve_json({"status": "ok"}))
    page.route(re.compile(r".*/state\?role=foreman$"), serve_json(state))
    page.route(
        re.compile(r".*/message$"),
        serve_json({"error": {"code": "invalid_request", "message": "Message rejected by the server."}}, status=422),
    )
    page.goto(f"{base_url}/chat/")
    page.get_by_label("Message or foreman command").fill("A test message")
    page.get_by_role("button", name="Send message").click()
    expect(page.locator("#notice")).to_contain_text("Message rejected by the server.")
    expect(page.locator(".member-bubble")).to_have_count(0)
    expect(page.get_by_role("button", name="Send message")).to_be_enabled()


def test_review_queue_empty_state_is_clear(page, base_url):
    state = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))
    state["flags"] = []
    page.route("**/health", serve_json({"status": "ok"}))
    page.route(re.compile(r".*/state\?role=foreman$"), serve_json(state))
    page.goto(f"{base_url}/chat/")
    expect(page.locator("#queue-status")).to_have_text("No open review items.")


def test_chat_shell_fits_mobile_viewport(page, base_url):
    state = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))
    page.route("**/health", serve_json({"status": "ok"}))
    page.route(re.compile(r".*/state\?role=foreman$"), serve_json(state))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{base_url}/chat/")
    expect(page.get_by_role("heading", name="ChitMirror Chat")).to_be_visible()
    expect(page.get_by_label("Sending as")).to_be_visible()
    expect(page.get_by_label("Message or foreman command")).to_be_visible()
    assert page.locator("body").evaluate("element => element.scrollWidth <= window.innerWidth")
