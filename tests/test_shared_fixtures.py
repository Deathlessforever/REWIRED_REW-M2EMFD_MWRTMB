"""Contract, referential-integrity, and financial checks for T04 fixtures."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "data" / "fixtures"
CONTRACTS = ROOT / "contracts"
SCHEMA = json.loads((CONTRACTS / "schemas.json").read_text(encoding="utf-8"))
STATE = json.loads((FIXTURES / "state_foreman.json").read_text(encoding="utf-8"))
RESULTS = json.loads((FIXTURES / "result_examples.json").read_text(encoding="utf-8"))
CHAT_REPLIES = {
    name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    for name in ("chat_dues_reply.json", "chat_statement_reply.json", "chat_reminder_reply.json")
}


def validator_for(name: str) -> Draft202012Validator:
    return Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{name}"}, format_checker=FormatChecker())


def csv_rows(name: str) -> list[dict[str, str]]:
    with (FIXTURES / name).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_contract_json_fixtures_validate_against_t01_schemas():
    validator_for("state_response").validate(STATE)
    expected = {"message_response", "review_request", "review_response", "reminders_request", "reminders_response", "demo_load_request", "demo_load_response", "error_response"}
    assert set(RESULTS) == expected
    for schema_name, instances in RESULTS.items():
        assert instances
        for instance in instances:
            validator_for(schema_name).validate(instance)
    for fixture in CHAT_REPLIES.values():
        validator_for("message_response").validate(fixture)


def test_result_examples_cover_every_t01_bubble_and_result_status():
    bubbles = RESULTS["message_response"][0]["bubbles"]
    assert {bubble["type"] for bubble in bubbles} == {"text", "result_card", "review_request", "reminder"}
    assert {bubble["status"] for bubble in bubbles if bubble["type"] == "result_card"} == {"verified", "duplicate", "wrong_amount", "needs_review"}


def test_state_has_twenty_unique_members_and_four_months_of_records():
    members = STATE["members"]
    member_ids = {member["id"] for member in members}
    assert len(members) == len(member_ids) == 20
    assert STATE["months"] == [1, 2, 3, 4]
    assert len(STATE["ledger"]) == 80
    assert {(entry["member_id"], entry["month"]) for entry in STATE["ledger"]} == {(member_id, month) for member_id in member_ids for month in STATE["months"]}


def test_references_counters_and_manual_review_are_consistent():
    member_ids = {member["id"] for member in STATE["members"]}
    ledger = STATE["ledger"]
    assert {entry["member_id"] for entry in ledger} <= member_ids
    assert {flag["member_id"] for flag in STATE["flags"]} <= member_ids
    assert all(flag["month"] in STATE["months"] for flag in STATE["flags"])
    review_entries = [entry for entry in ledger if entry["status"] == "needs_review"]
    assert len(review_entries) == STATE["counters"]["needs_review"] == 2
    assert all(entry["utr"] is None for entry in review_entries)
    assert STATE["counters"]["paid"] == sum(entry["status"] == "verified" for entry in ledger)
    assert STATE["counters"]["collected_paise"] == sum(entry["amount_paise"] for entry in ledger if entry["status"] == "verified")
    assert STATE["counters"]["overdue"] == len(STATE["overdue"]) == 2
    required_actions = {"payment_submitted", "payment_processed", "payment_claimed", "payment_verified", "payment_rejected", "admin_override", "member_reassigned"}
    assert required_actions <= {event["action"] for event in STATE["audit_log"]}
    assert len({event["id"] for event in STATE["audit_log"]}) == len(STATE["audit_log"])
    assert all(member["name"] == f"Member {index:02d}" for index, member in enumerate(STATE["members"], start=1))


def test_evidence_is_unique_and_only_verifies_matching_payment_claims():
    evidence = csv_rows("bank_evidence.csv")
    assert evidence
    assert len({row["utr"] for row in evidence}) == len(evidence)
    verified = {entry["utr"]: entry for entry in STATE["ledger"] if entry["status"] == "verified"}
    all_utr_values = [entry["utr"] for entry in STATE["ledger"] if entry["utr"] is not None]
    assert len(all_utr_values) == len(set(all_utr_values))
    assert set(row["utr"] for row in evidence) == set(verified)
    for row in evidence:
        payment = verified[row["utr"]]
        assert int(row["amount_paise"]) == payment["amount_paise"]
        assert row["group_id"] == "group-synthetic-01"
    assert not {entry["utr"] for entry in STATE["ledger"] if entry["status"] != "verified" and entry["utr"]} & set(verified)


def test_schedule_reconciles_and_ledger_uses_each_cycle_amount():
    rows = csv_rows("financial_schedule.csv")
    assert len(rows) == 4
    members = {member["id"] for member in STATE["members"]}
    for row in rows:
        month = int(row["month"])
        value = int(row["chit_value_paise"])
        count = int(row["member_count"])
        commission = int(row["commission_paise"])
        discount = int(row["winning_discount_paise"])
        prize = int(row["prize_paise"])
        surplus = int(row["surplus_paise"])
        dividend = int(row["dividend_per_member_paise"])
        expected = int(row["expected_instalment_paise"])
        assert row["group_id"] == "group-synthetic-01"
        assert row["winner_member_id"] in members
        assert prize == value - discount
        assert surplus == discount - commission
        assert dividend == surplus // count
        assert expected == value // count - dividend
        assert int(row["expected_pool_paise"]) == expected * count == prize + commission
        for entry in (item for item in STATE["ledger"] if item["month"] == month):
            if entry["status"] == "rejected":
                assert entry["amount_paise"] != expected
            else:
                assert entry["amount_paise"] == expected
