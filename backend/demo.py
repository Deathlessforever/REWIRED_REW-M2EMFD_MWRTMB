"""Synthetic four-month demo loader and planted-payment scenario runner."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import json
from pathlib import Path

from backend.database import audited_transaction

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
SEED_ID = "chitmirror-four-month-demo-v1"
SEED_REASON = "Load synthetic four-month ChitMirror demo"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _evaluate_claim(claim: dict, evidence_by_utr: dict[str, dict[str, str]],
                    previously_used: set[str], *, receiver_upi_id: str,
                    due_date: date) -> dict:
    utr = claim.get("utr")
    amount = claim.get("amount_paise")
    evidence = evidence_by_utr.get(utr)
    transaction_date = date.fromisoformat(claim["transaction_date"]) if claim.get("transaction_date") else None
    timing = "late" if transaction_date and transaction_date > due_date else "on_time"

    if utr in previously_used:
        return {
            "bubble": {"type": "result_card", "status": "duplicate", "amount_paise": amount,
                       "utr": utr, "reason": "UTR already used in the group ledger."},
            "ledger": {"recorded": False, "timing": timing},
        }
    if evidence is None:
        return {
            "bubble": {"type": "result_card", "status": "needs_review", "amount_paise": amount,
                       "utr": None, "reason": "UTR not found in bank CSV."},
            "ledger": {"recorded": False, "timing": "unknown"},
        }
    if (evidence.get("bank_status") != "SETTLED"
            or evidence.get("receiver_upi_id") != receiver_upi_id
            or evidence.get("payer_member_id") != claim.get("member_id")):
        return {
            "bubble": {"type": "result_card", "status": "needs_review", "amount_paise": amount,
                       "utr": None, "reason": "Payment details do not match independent bank evidence."},
            "ledger": {"recorded": False, "timing": timing},
        }

    evidence_amount = int(evidence["amount_paise"])
    if amount != evidence_amount:
        return {
            "bubble": {"type": "result_card", "status": "wrong_amount", "amount_paise": amount,
                       "utr": utr,
                       "reason": f"Expected {evidence_amount} paise from independent bank evidence."},
            "ledger": {"recorded": False, "timing": timing},
        }

    credited = date.fromisoformat(evidence["transaction_date"])
    late = credited > due_date
    reason = "Matched independent bank evidence."
    ledger = {"recorded": True, "timing": "on_time"}
    if late:
        reason = f"Matched bank evidence; transaction arrived after the {due_date.isoformat()} due date."
        ledger = {"recorded": True, "status": "overdue", "timing": "late", "late_fee_paise": None}
    return {
        "bubble": {"type": "result_card", "status": "verified", "amount_paise": evidence_amount,
                   "utr": utr, "reason": reason},
        "ledger": ledger,
    }


def run_planted_scenarios(data_root: Path = DATA_ROOT) -> list[dict]:
    """Execute each synthetic claim against the planted bank CSV and compare its expected result."""
    demo = _json(data_root / "demo_chit.json")
    scenario_doc = _json(data_root / "scenarios.json")
    bank_rows = _csv(data_root / "bank.csv")
    evidence_by_utr = {row["utr"]: row for row in bank_rows}
    if len(evidence_by_utr) != len(bank_rows):
        raise ValueError("T06 bank CSV contains duplicate UTRs.")
    reused = {row["utr"] for row in bank_rows if row.get("scenario_tag") == "reused_utr_source"}
    due_date = date.fromisoformat(demo["group"]["due_date"])
    results = []
    for scenario in scenario_doc.get("scenarios", []):
        actual = _evaluate_claim(
            scenario["claim"], evidence_by_utr, reused,
            receiver_upi_id=demo["group"]["group_upi_id"], due_date=due_date,
        )
        expected = scenario["expected_result"]
        if actual != expected:
            raise ValueError(f"Planted scenario {scenario.get('id')} did not match its expected result.")
        results.append({"id": scenario["id"], "result": actual})
    if len(results) != 5:
        raise ValueError("Demo plan must exercise all five planted payment scenarios.")
    return results


def _read_four_month_data(data_root: Path):
    state = _json(data_root / "fixtures" / "state_foreman.json")
    schedule = _csv(data_root / "fixtures" / "financial_schedule.csv")
    evidence = _csv(data_root / "fixtures" / "bank_evidence.csv")
    if state.get("months") != [1, 2, 3, 4] or len(state.get("members", [])) != 20 or len(state.get("ledger", [])) != 80:
        raise ValueError("The four-month fixture must contain 20 members and 80 ledger cells.")
    if len(schedule) != 4 or {int(row["month"]) for row in schedule} != {1, 2, 3, 4}:
        raise ValueError("The financial schedule must contain months 1 through 4.")

    evidence_by_utr = {row["utr"]: row for row in evidence}
    if len(evidence_by_utr) != len(evidence):
        raise ValueError("Shared bank evidence contains duplicate UTRs.")
    verified = [entry for entry in state["ledger"] if entry["status"] == "verified"]
    if len(evidence) != len(verified):
        raise ValueError("Shared bank evidence must match the verified fixture rows exactly.")
    expected_utrs = set()
    for entry in verified:
        utr = entry.get("utr")
        row = evidence_by_utr.get(utr)
        expected_reference = "synthetic-" + entry["member_id"]
        if (row is None or int(row["amount_paise"]) != entry["amount_paise"]
                or row["payer_reference"] != expected_reference
                or int(utr[:2]) != entry["month"]
                or row["group_id"] != schedule[0]["group_id"]):
            raise ValueError("Verified ledger fixture row lacks matching independent bank evidence.")
        expected_utrs.add(utr)
    if set(evidence_by_utr) != expected_utrs:
        raise ValueError("Bank CSV contains evidence outside the verified ledger rows.")

    schedule_by_month = {int(row["month"]): row for row in schedule}
    for entry in state["ledger"]:
        if entry["status"] not in {"verified", "rejected", "needs_review", "overdue", "pending"}:
            raise ValueError("Shared ledger fixture contains an unsupported payment status.")
        if entry["status"] != "verified" and entry.get("utr") in evidence_by_utr:
            raise ValueError("A non-verified fixture payment cannot match bank evidence.")
        if entry["amount_paise"] != int(schedule_by_month[entry["month"]]["expected_instalment_paise"]) and entry["status"] not in {"rejected"}:
            raise ValueError("Non-rejected fixture amount does not match its monthly schedule.")
    return state, schedule, evidence


def _seed_counts(db):
    return {
        "members": db.execute("SELECT COUNT(*) FROM members").fetchone()[0],
        "months": db.execute("SELECT COUNT(*) FROM months").fetchone()[0],
        "payments": db.execute("SELECT COUNT(*) FROM payments").fetchone()[0],
        "payment_entries": db.execute("SELECT COUNT(*) FROM ledger_entries WHERE kind='payment'").fetchone()[0],
        "bank_evidence": db.execute("SELECT COUNT(*) FROM bank_evidence").fetchone()[0],
    }


def load_demo(db, context, *, actor: str, data_root: Path = DATA_ROOT) -> dict:
    """Load the synthetic four-month ledger once, without clearing existing data."""
    if actor != "foreman":
        raise ValueError("only the foreman can load demo data.")
    state, schedule, evidence = _read_four_month_data(data_root)
    run_planted_scenarios(data_root)
    expected_counts = {
        "members": len(state["members"]),
        "months": 4,
        "payments": sum(entry["status"] in {"verified", "rejected", "needs_review"} for entry in state["ledger"]),
        "payment_entries": sum(entry["status"] == "verified" for entry in state["ledger"]),
        "bank_evidence": len(evidence),
    }

    with audited_transaction(db, context, actor=actor, reason=SEED_REASON):
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM demo_loads WHERE seed_id=?", (SEED_ID,)).fetchone():
            return {"loaded": True}
        occupied = any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in (
            "members", "months", "payments", "ledger_entries", "settlements",
            "settlement_dues", "reminders", "bank_evidence", "audit_log",
        ))
        if occupied:
            raise ValueError("Demo loading requires an empty demo database; existing records were left untouched.")

        # Preserve the fixture's synthetic history before recording the loader's audit rows.
        db.executemany(
            "INSERT INTO audit_log(actor, action, reason, timestamp, entity_id) VALUES (?, ?, ?, ?, ?)",
            [(event["actor"], event["action"], event["reason"], event["timestamp"], event["id"])
             for event in state["audit_log"]],
        )
        db.executemany("INSERT INTO members(id, name) VALUES (?, ?)",
                       [(member["id"], member["name"]) for member in state["members"]])
        db.executemany("INSERT INTO months(month, due_date) VALUES (?, ?)",
                       [(int(row["month"]), row["due_date"]) for row in schedule])
        db.executemany(
            "INSERT INTO bank_evidence(evidence_id, group_id, utr, amount_paise, credited_at, payer_reference) VALUES (?, ?, ?, ?, ?, ?)",
            [(row["evidence_id"], row["group_id"], row["utr"], int(row["amount_paise"]),
              row["credited_at"], row["payer_reference"]) for row in evidence],
        )

        evidence_by_utr = {row["utr"]: row for row in evidence}
        for entry in state["ledger"]:
            if entry["status"] not in {"verified", "rejected", "needs_review"}:
                continue
            payment_id = f"demo-m{entry['month']:02d}-{entry['member_id']}"
            if entry["status"] == "verified":
                proof = evidence_by_utr[entry["utr"]]
                if int(proof["amount_paise"]) != entry["amount_paise"]:
                    raise ValueError("Verified payment amount did not match independent bank evidence.")
            db.execute(
                "INSERT INTO payments(id, member_id, month, amount_paise, utr, status) VALUES (?, ?, ?, ?, ?, ?)",
                (payment_id, entry["member_id"], entry["month"], entry["amount_paise"], entry["utr"], entry["status"]),
            )
            if entry["status"] == "verified":
                db.execute(
                    "INSERT INTO ledger_entries(id, member_id, month, payment_id, amount_paise, kind) VALUES (?, ?, ?, ?, ?, 'payment')",
                    ("demo-ledger-" + payment_id, entry["member_id"], entry["month"], payment_id, entry["amount_paise"]),
                )

        loaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        db.execute("INSERT INTO demo_loads(seed_id, fixture_version, loaded_at) VALUES (?, ?, ?)",
                   (SEED_ID, 1, loaded_at))
        if _seed_counts(db) != expected_counts:
            raise ValueError("Loaded demo record counts did not match the fixture.")
    return {"loaded": True}
