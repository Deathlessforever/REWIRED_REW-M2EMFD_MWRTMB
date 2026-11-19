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
      const command = await fetch(base + '/message', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({sender: 'member-07', text: 'statement'})}).then(r => r.json());
      return {base, members: state.members.length, months: state.months.length, status: reply.bubbles[0].status, statement: command.bubbles[0].text.includes('Statement for Member 07')};
    }""")
    assert result == {"base": "http://127.0.0.1:8001", "members": 20, "months": 4, "status": "wrong_amount", "statement": True}
