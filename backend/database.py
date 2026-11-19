"""SQLite storage primitives; all domain mutations require an audit context."""

from contextlib import contextmanager
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0)
);
CREATE TABLE IF NOT EXISTS months (
    month INTEGER PRIMARY KEY CHECK(month > 0),
    due_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id),
    month INTEGER NOT NULL REFERENCES months(month),
    amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
    utr TEXT,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_entries (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id),
    month INTEGER NOT NULL REFERENCES months(month),
    payment_id TEXT REFERENCES payments(id),
    amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
    kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settlements (
    month INTEGER PRIMARY KEY REFERENCES months(month),
    winner_id TEXT NOT NULL REFERENCES members(id),
    discount_paise INTEGER NOT NULL CHECK(discount_paise >= 0),
    prize_paise INTEGER NOT NULL CHECK(prize_paise >= 0),
    commission_paise INTEGER NOT NULL CHECK(commission_paise >= 0),
    tag_total_paise INTEGER NOT NULL CHECK(tag_total_paise >= 0)
);
CREATE TABLE IF NOT EXISTS settlement_dues (
    month INTEGER NOT NULL REFERENCES settlements(month),
    member_id TEXT NOT NULL REFERENCES members(id),
    base_due_paise INTEGER NOT NULL CHECK(base_due_paise >= 0),
    tag_paise INTEGER NOT NULL CHECK(tag_paise BETWEEN 1 AND 99),
    dividend_paise INTEGER NOT NULL CHECK(dividend_paise >= 0),
    PRIMARY KEY(month, member_id)
);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id),
    month INTEGER NOT NULL REFERENCES months(month),
    phase TEXT NOT NULL CHECK(phase IN ('before', 'due', 'overdue')),
    send_date TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(member_id, month, phase, send_date)
);
CREATE TABLE IF NOT EXISTS bank_evidence (
    evidence_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    utr TEXT NOT NULL UNIQUE CHECK(length(utr) = 12 AND utr NOT GLOB '*[^0-9]*'),
    amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
    credited_at TEXT NOT NULL,
    payer_reference TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_loads (
    seed_id TEXT PRIMARY KEY,
    fixture_version INTEGER NOT NULL,
    loaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL CHECK(length(trim(actor)) > 0),
    action TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    timestamp TEXT NOT NULL,
    entity_id TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ledger_one_payment_per_month
ON ledger_entries(member_id, month) WHERE kind = 'payment';
CREATE UNIQUE INDEX IF NOT EXISTS ledger_one_posting_per_payment
ON ledger_entries(payment_id) WHERE kind = 'payment' AND payment_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ledger_one_late_fee_per_payment
ON ledger_entries(payment_id) WHERE kind = 'late_fee' AND payment_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ledger_one_prize_per_month
ON ledger_entries(month) WHERE kind = 'prize';
CREATE UNIQUE INDEX IF NOT EXISTS ledger_one_dividend_per_member_month
ON ledger_entries(member_id, month) WHERE kind = 'dividend';
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_replace BEFORE INSERT ON audit_log
WHEN EXISTS (SELECT 1 FROM audit_log WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_replace BEFORE INSERT ON ledger_entries
WHEN EXISTS (SELECT 1 FROM ledger_entries WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS settlement_no_update BEFORE UPDATE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlement is immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlement_no_delete BEFORE DELETE ON settlements
BEGIN SELECT RAISE(ABORT, 'settlement is immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlement_no_replace BEFORE INSERT ON settlements
WHEN EXISTS (SELECT 1 FROM settlements WHERE month = NEW.month)
BEGIN SELECT RAISE(ABORT, 'settlement is immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlement_due_no_update BEFORE UPDATE ON settlement_dues
BEGIN SELECT RAISE(ABORT, 'settlement due is immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlement_due_no_delete BEFORE DELETE ON settlement_dues
BEGIN SELECT RAISE(ABORT, 'settlement due is immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlement_due_no_replace BEFORE INSERT ON settlement_dues
WHEN EXISTS (SELECT 1 FROM settlement_dues WHERE month = NEW.month AND member_id = NEW.member_id)
BEGIN SELECT RAISE(ABORT, 'settlement due is immutable'); END;
CREATE TRIGGER IF NOT EXISTS reminder_no_update BEFORE UPDATE ON reminders
BEGIN SELECT RAISE(ABORT, 'reminders are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reminder_no_delete BEFORE DELETE ON reminders
BEGIN SELECT RAISE(ABORT, 'reminders are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reminder_no_replace BEFORE INSERT ON reminders
WHEN EXISTS (SELECT 1 FROM reminders WHERE id = NEW.id OR
             (member_id = NEW.member_id AND month = NEW.month AND phase = NEW.phase AND send_date = NEW.send_date))
BEGIN SELECT RAISE(ABORT, 'reminders are append-only'); END;
CREATE TRIGGER IF NOT EXISTS bank_evidence_no_update BEFORE UPDATE ON bank_evidence
BEGIN SELECT RAISE(ABORT, 'bank evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS bank_evidence_no_delete BEFORE DELETE ON bank_evidence
BEGIN SELECT RAISE(ABORT, 'bank evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS bank_evidence_no_replace BEFORE INSERT ON bank_evidence
WHEN EXISTS (SELECT 1 FROM bank_evidence WHERE evidence_id = NEW.evidence_id OR utr = NEW.utr)
BEGIN SELECT RAISE(ABORT, 'bank evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS demo_load_no_update BEFORE UPDATE ON demo_loads
BEGIN SELECT RAISE(ABORT, 'demo load marker is immutable'); END;
CREATE TRIGGER IF NOT EXISTS demo_load_no_delete BEFORE DELETE ON demo_loads
BEGIN SELECT RAISE(ABORT, 'demo load marker is immutable'); END;
CREATE TRIGGER IF NOT EXISTS demo_load_no_replace BEFORE INSERT ON demo_loads
WHEN EXISTS (SELECT 1 FROM demo_loads WHERE seed_id = NEW.seed_id)
BEGIN SELECT RAISE(ABORT, 'demo load marker is immutable'); END;
"""


def connect(path):
    """Open an initialized connection; use audited_transaction for domain writes."""
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    # REPLACE deletes the previous row: recursive triggers must catch it.
    db.execute("PRAGMA recursive_triggers = ON")
    context = {"actor": None, "reason": None}
    db.create_function("audit_actor", 0, lambda: context["actor"])
    db.create_function("audit_reason", 0, lambda: context["reason"])
    db.executescript(SCHEMA)
    for table, key in (("members", "id"), ("months", "month"), ("payments", "id"), ("ledger_entries", "id"), ("settlements", "month"), ("settlement_dues", "member_id"), ("reminders", "id"), ("bank_evidence", "evidence_id"), ("demo_loads", "seed_id")):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            row = "OLD" if operation == "DELETE" else "NEW"
            db.execute(f"""
                CREATE TRIGGER IF NOT EXISTS audit_{table}_{operation.lower()}
                AFTER {operation} ON {table}
                BEGIN
                  INSERT INTO audit_log(actor, action, reason, timestamp, entity_id)
                  VALUES (audit_actor(), '{table}.{operation.lower()}', audit_reason(),
                          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), CAST({row}.{key} AS TEXT));
                END
            """)
    return db, context


@contextmanager
def audited_transaction(db, context, *, actor, reason):
    """Commit domain writes and their audit rows atomically or roll back both."""
    if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
        raise ValueError("actor and reason are required")
    if db.in_transaction or context["actor"] is not None:
        raise RuntimeError("nested or already active transactions are not supported")
    context.update(actor=actor, reason=reason)
    try:
        with db:
            yield db
    finally:
        context.update(actor=None, reason=None)
