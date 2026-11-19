import os

import pytest
from playwright.sync_api import expect


@pytest.mark.skipif(os.environ.get("CHITMIRROR_TEST_STUB") != "1", reason="requires separate stub and frontend servers")
@pytest.mark.parametrize("page_path", ["chat", "dashboard"])
def test_ui_uses_shared_backend_environment(page, base_url, page_path):
    page.goto(f"{base_url}/{page_path}/")
    expect(page.locator("body")).to_be_visible()
    result = page.evaluate("""async () => {
      const base = window.CHITMIRROR_API_BASE;
      const state = await fetch(base + '/state?role=foreman').then(r => r.json());
      const form = new FormData();
      form.append('sender', 'member-07');
      form.append('text', 'stub:wrong_amount');
      const reply = await fetch(base + '/message', {method: 'POST', body: form}).then(r => r.json());
      return {base, members: state.members.length, months: state.months.length, status: reply.bubbles[0].status};
    }""")
    assert result == {"base": "http://127.0.0.1:8001", "members": 20, "months": 4, "status": "wrong_amount"}


@pytest.mark.skipif(os.environ.get("CHITMIRROR_TEST_STUB") != "1", reason="requires separate stub and frontend servers")
def test_chat_sends_message_to_real_stub_and_renders_reply(page, base_url):
    console_errors = []
    failed_api_requests = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("requestfailed", lambda request: failed_api_requests.append(request.url) if ":8001/" in request.url else None)

    page.goto(f"{base_url}/chat/")
    expect(page.get_by_role("heading", name="ChitMirror Chat")).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="Backend connected")).to_be_visible()

    sender = page.get_by_label("Sending as")
    expect(sender.locator("option").filter(has_text="Foreman")).to_have_count(1)
    expect(sender.locator("option").filter(has_text="Member 07")).to_have_count(1)
    sender.select_option("member-07")
    expect(sender).to_have_value("member-07")

    with page.expect_response(lambda response: response.url.endswith("/message") and response.request.method == "POST") as response_info:
        page.get_by_label("Message or foreman command").fill("stub:wrong_amount")
        page.get_by_role("button", name="Send message").click()

    response = response_info.value
    assert response.status == 200
    assert ":8001/message" in response.url
    assert 'name="sender"' in response.request.post_data
    assert "member-07" in response.request.post_data
    assert "stub:wrong_amount" in response.request.post_data

    reply = response.json()["bubbles"][0]
    assert reply["type"] == "result_card"
    assert reply["status"] == "wrong_amount"
    expect(page.locator(".member-bubble").filter(has_text="stub:wrong_amount")).to_be_visible()
    result_card = page.locator(".result-bubble")
    expect(result_card).to_contain_text("wrong_amount")
    timestamp = result_card.locator("time")
    expect(timestamp).to_be_visible()
    assert timestamp.get_attribute("datetime")
    assert not console_errors
    assert not failed_api_requests
