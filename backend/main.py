"""Local demo API for ChitMirror's dashboard and seeded payment ledger."""

from __future__ import annotations

import copy
import csv
import json
import re
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
app = FastAPI(title="ChitMirror", version="0.1.0")
STATE_LOCK = threading.RLock()


def read_evidence() -> dict[str, Any]:
    dashboard = json.loads((DATA / "dashboard.json").read_text(encoding="utf-8"))
    with (DATA / "bank.csv").open(newline="", encoding="utf-8") as csv_file:
        transactions = list(csv.DictReader(csv_file))
    for transaction in transactions:
        transaction["amount"] = int(transaction["amount"])
    dashboard["transactions"] = transactions
    return dashboard


EVIDENCE = read_evidence()


def seed_state() -> dict[str, Any]:
    verified_utrs = set(EVIDENCE["initialVerifiedUtrs"])
    payments = [
        {
            "utr": transaction["utr"],
            "amount": transaction["amount"],
            "memberId": transaction["memberId"],
            "memberName": transaction["memberName"],
            "month": EVIDENCE["group"]["currentMonth"],
            "time": "2024-12-05T10:00:00+05:30",
        }
        for transaction in EVIDENCE["transactions"]
        if transaction["utr"] in verified_utrs
    ]
    members = {member["memberId"]: member["memberName"] for member in EVIDENCE["transactions"]}
    audit = [
        {**event, "memberName": event.get("memberName") or members.get(event["memberId"], "Unmatched")}
        for event in EVIDENCE["initialAudit"]
    ]
    return {"payments": payments, "audit": audit, "month": EVIDENCE["group"]["currentMonth"]}


STATE = seed_state()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    with STATE_LOCK:
        return {"state": copy.deepcopy(STATE), "evidence": copy.deepcopy(EVIDENCE)}


@app.post("/api/verify")
def verify_payment(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    utr = re.sub(r"\s+", "", str(fields.get("utr", ""))).upper()
    receiver = str(fields.get("receiver", "")).strip()
    transaction_date = str(fields.get("date", "")).strip()
    member_id = str(fields.get("memberId", "")).strip()
    try:
        amount = Decimal(str(fields.get("amount", "")).replace(",", ""))
        if not amount.is_finite():
            amount = Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")

    transactions = EVIDENCE["transactions"]
    member = next((item for item in transactions if item["memberId"] == member_id), None)
    record = next((item for item in transactions if item["utr"].upper() == utr), None)
    time = datetime.now().astimezone().isoformat(timespec="seconds")

    with STATE_LOCK:
        if not utr or not fields.get("amount") or not receiver or not transaction_date or not member_id or amount <= 0:
            status, reason = "review", "UTR, positive amount, date, receiver and member are required."
        elif not re.fullmatch(r"\d{12}", utr):
            status, reason = "review", "Transaction reference must contain exactly 12 digits."
        elif any(payment["utr"].upper() == utr for payment in STATE["payments"]):
            status, reason = "duplicate", "This UTR has already been recorded in the group ledger."
        elif not record:
            status, reason = "failed", "No matching transaction exists in the independent bank CSV."
        elif Decimal(str(record["amount"])) != amount:
            status, reason = "mismatch", f"Amount mismatch: bank evidence shows ₹{record['amount']:,}."
        elif record["receiver"].casefold() != receiver.casefold():
            status, reason = "mismatch", f"Receiver mismatch: evidence is for {record['receiver']}."
        elif record["date"] != transaction_date:
            status, reason = "mismatch", f"Date mismatch: evidence is dated {record['date']}."
        elif record["memberId"] != member_id:
            status, reason = "mismatch", f"This transaction belongs to {record['memberName']}, not the selected member."
        else:
            status, reason = "verified", "UTR, amount, date, receiver and member match independent bank evidence."

        result = {
            "status": status,
            "reason": reason,
            "utr": utr,
            "amount": float(amount),
            "receiver": receiver,
            "date": transaction_date,
            "memberId": member_id,
            "memberName": member["memberName"] if member else "Unmatched",
            "fileName": str(payload.get("fileName", "")),
            "time": time,
        }
        STATE["audit"].insert(0, result)
        if status == "verified":
            result["memberName"] = record["memberName"]
            STATE["payments"].append(
                {
                    "utr": utr,
                    "amount": float(amount),
                    "memberId": record["memberId"],
                    "memberName": record["memberName"],
                    "month": STATE["month"],
                    "time": time,
                }
            )
        return {"result": copy.deepcopy(result), "state": copy.deepcopy(STATE)}


@app.post("/api/reset")
def reset_demo() -> dict[str, Any]:
    global STATE
    with STATE_LOCK:
        STATE = seed_state()
        return copy.deepcopy(STATE)


# Serve both frontends and local synthetic evidence on the same origin.
app.mount("/chat", StaticFiles(directory=ROOT / "chat-ui", html=True), name="chat")
app.mount("/dashboard", StaticFiles(directory=ROOT / "dashboard", html=True), name="dashboard")
app.mount("/data", StaticFiles(directory=DATA), name="data")

