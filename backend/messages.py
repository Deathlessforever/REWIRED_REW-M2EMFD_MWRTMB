"""Member chat commands built from the shared state contract."""

import re

from backend.state import get_state


COMMAND_PATTERNS = (
    ("statement", re.compile(r"\bstatements?\b", re.IGNORECASE)),
    ("dues", re.compile(r"\bdues?\b|\bamount due\b", re.IGNORECASE)),
    ("reminders", re.compile(r"\breminders?\b", re.IGNORECASE)),
)


def format_paise(paise):
    try:
        amount = int(paise)
    except (TypeError, ValueError):
        return "not available"
    return f"₹{amount / 100:,.2f}"


def command_for(text):
    for name, pattern in COMMAND_PATTERNS:
        if pattern.search(text or ""):
            return name
    return None


def member_name(state, member_id):
    for member in state["members"]:
        if member["id"] == member_id:
            return member["name"]
    return member_id


def dues_reply(db, state, sender):
    months = [int(month) for month in state["months"] if str(month).isdigit()]
    current = months[-1] if months else None
    due_row = db.execute("SELECT due_date FROM months WHERE month = ?", (current,)).fetchone() if current else None
    due_date = due_row[0] if due_row else None
    entry = next((item for item in state["ledger"] if item["member_id"] == sender and item["month"] == current), None)
    parts = [f"Dues for {member_name(state, sender)}"]
    if current:
        parts.append(f"month {current}")
    if due_date:
        parts.append(f"due {due_date}")
    if entry:
        parts.append(f"status: {entry['status'].replace('_', ' ')}")
        amount = format_paise(entry["amount_paise"]) if entry["amount_paise"] else "not available"
        parts.append(f"amount: {amount}")
    else:
        parts.append("status: no payment recorded")
        parts.append("amount: not available")
    parts.append("This is a shared-state summary; independent bank evidence controls verification.")
    return {"type": "text", "text": ". ".join(parts)}


def statement_reply(state, sender):
    rows = state["statement"]
    name = member_name(state, sender)
    if not rows:
        return {"type": "text", "text": f"No statement entries are available for {name}."}
    lines = [
        f"Statement for {name}",
        "The shared statement schema includes month, instalment, dividend, late fee, prize and status; dates, descriptions and running balances are not provided.",
    ]
    for row in rows:
        lines.append(
            f"Month {row['month']} · instalment {format_paise(row['instalment_paise'])} · "
            f"dividend {format_paise(row['dividend_paise'])} · late fee {format_paise(row['late_fee_paise'])} · "
            f"prize {format_paise(row['prize_paise'])} · {row['status']}"
        )
    return {"type": "text", "text": "\n".join(lines)}


def reminders_reply(state, sender):
    bubbles = list(state["private_bubbles"])
    if not bubbles:
        return [{"type": "text", "text": f"No private reminders are available for {member_name(state, sender)}."}]
    return [{"type": "text", "text": f"Private reminders for {member_name(state, sender)}"}] + bubbles


def handle_message(db, *, sender, text):
    """Return bubbles for the selected sender; never accept a target member ID."""
    if sender == "foreman":
        return {"bubbles": [{"type": "text", "text": "Foreman commands stay in the shared contract. Review decisions are handled in the review queue."}]}
    state = get_state(db, role="member", member_id=sender)
    command = command_for(text)
    if command == "dues":
        bubbles = [dues_reply(db, state, sender)]
    elif command == "statement":
        bubbles = [statement_reply(state, sender)]
    elif command == "reminders":
        bubbles = reminders_reply(state, sender)
    else:
        bubbles = [{"type": "text", "text": "Try: dues, statement or reminders. The reply uses your selected member only."}]
    return {"bubbles": bubbles}
