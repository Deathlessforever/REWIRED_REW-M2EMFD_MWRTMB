"""Deterministic pre-classification checks for unverified payment claims.

OCR output is untrusted input. This module only compares a claim with expected
values and independent bank evidence; it never creates a payment, changes a
ledger, or decides that a payment is verified. T15 owns result classification.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


UTR_PATTERN = re.compile(r"^[0-9]{12}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ExtractedPaymentClaim:
    """Fields may be null because the screenshot reader must not fabricate them."""

    member_id: str | None
    utr: str | None
    amount_paise: int | None
    receiver_upi_id: str | None
    image_sha256: str | None = None
    integrity_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BankEvidence:
    utr: str
    amount_paise: int
    amount_tag: str
    receiver_upi_id: str
    payer_member_id: str
    bank_status: str


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    code: str
    reason: str


@dataclass(frozen=True)
class PaymentCheckReport:
    """An auditable collection of check outcomes; it is not a payment decision."""

    claim: ExtractedPaymentClaim
    expected_amount_paise: int
    expected_receiver_upi_id: str
    evidence: BankEvidence | None
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def by_name(self, name: str) -> CheckResult:
        return next(check for check in self.checks if check.name == name)


class ImageHashRegistry(Protocol):
    """Persistence boundary: callers can substitute durable storage later."""

    def contains(self, image_sha256: str) -> bool: ...

    def record(self, image_sha256: str) -> None: ...


class InMemoryImageHashRegistry:
    """Test/demo implementation. Recording is explicit, separate from checking."""

    def __init__(self, known_hashes: Iterable[str] = ()) -> None:
        self._hashes = set(known_hashes)

    def contains(self, image_sha256: str) -> bool:
        return image_sha256 in self._hashes

    def record(self, image_sha256: str) -> None:
        if not SHA256_PATTERN.fullmatch(image_sha256):
            raise ValueError("image SHA-256 must be a lowercase 64-character hex string")
        self._hashes.add(image_sha256)


def load_bank_evidence(csv_path: Path) -> dict[str, BankEvidence]:
    """Load synthetic or independent bank CSV evidence keyed by 12-digit UTR."""
    evidence: dict[str, BankEvidence] = {}
    with csv_path.open(newline="", encoding="utf-8") as stream:
        for line_number, row in enumerate(csv.DictReader(stream), start=2):
            utr = row.get("utr", "")
            if not UTR_PATTERN.fullmatch(utr):
                raise ValueError(f"bank CSV row {line_number} has an invalid UTR")
            if utr in evidence:
                raise ValueError(f"bank CSV has duplicate UTR {utr}")
            try:
                amount_paise = int(row["amount_paise"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"bank CSV row {line_number} has an invalid amount_paise") from error
            if amount_paise < 0:
                raise ValueError(f"bank CSV row {line_number} has a negative amount_paise")
            evidence[utr] = BankEvidence(
                utr=utr,
                amount_paise=amount_paise,
                amount_tag=row.get("amount_tag", "").strip(),
                receiver_upi_id=row.get("receiver_upi_id", ""),
                payer_member_id=row.get("payer_member_id", ""),
                bank_status=row.get("bank_status", ""),
            )
    return evidence


def validate_payment_claim(
    claim: ExtractedPaymentClaim,
    *,
    expected_amount_paise: int,
    expected_receiver_upi_id: str,
    evidence_by_utr: dict[str, BankEvidence],
    used_utrs: Iterable[str] | None = None,
    image_hash_registry: ImageHashRegistry | None = None,
) -> PaymentCheckReport:
    """Check claim data against expected values and independent evidence.

    A fully passing report remains only a candidate for T15. The caller must not
    treat this report or OCR confidence as verification by itself.
    """
    if type(expected_amount_paise) is not int or expected_amount_paise < 0:
        raise ValueError("expected_amount_paise must be a non-negative integer")
    if not isinstance(expected_receiver_upi_id, str) or not expected_receiver_upi_id.strip():
        raise ValueError("expected_receiver_upi_id is required")
    used = set(used_utrs) if used_utrs is not None else None
    valid_utr = isinstance(claim.utr, str) and UTR_PATTERN.fullmatch(claim.utr) is not None
    checks: list[CheckResult] = []
    if claim.utr is None:
        checks.append(CheckResult("utr_format", False, "missing_utr", "Transaction reference is missing from the screenshot claim."))
    elif not valid_utr:
        checks.append(CheckResult("utr_format", False, "invalid_utr", "Transaction reference must contain exactly 12 digits."))
    else:
        checks.append(CheckResult("utr_format", True, "valid_utr", "Transaction reference has the required 12-digit format."))

    if type(claim.amount_paise) is not int or claim.amount_paise < 0:
        checks.append(CheckResult("expected_amount", False, "missing_or_invalid_amount", "Payment amount is missing or invalid."))
    elif claim.amount_paise != expected_amount_paise:
        checks.append(CheckResult("expected_amount", False, "wrong_amount", f"Expected {expected_amount_paise} paise, received {claim.amount_paise} paise."))
    else:
        checks.append(CheckResult("expected_amount", True, "amount_matches", "Screenshot claim amount matches the expected instalment."))

    if not claim.receiver_upi_id:
        checks.append(CheckResult("payee", False, "missing_payee", "Receiver UPI ID is missing from the screenshot claim."))
    elif claim.receiver_upi_id != expected_receiver_upi_id:
        checks.append(CheckResult("payee", False, "wrong_payee", "Receiver UPI ID does not match the group payee."))
    else:
        checks.append(CheckResult("payee", True, "payee_matches", "Screenshot claim payee matches the group payee."))

    evidence = evidence_by_utr.get(claim.utr) if valid_utr else None
    if evidence is None:
        checks.append(CheckResult("bank_evidence", False, "utr_not_in_bank_csv", "No independent bank evidence matches this transaction reference."))
    elif evidence.utr != claim.utr:
        checks.append(CheckResult("bank_evidence", False, "bank_reference_conflict", "Independent bank evidence has a different transaction reference."))
    elif evidence.bank_status != "SETTLED":
        checks.append(CheckResult("bank_evidence", False, "bank_not_settled", "Independent bank evidence is not settled."))
    elif not evidence.amount_tag:
        checks.append(CheckResult("bank_evidence", False, "bank_missing_amount_tag", "Independent bank evidence does not identify the payment amount type."))
    elif evidence.amount_paise != claim.amount_paise:
        checks.append(CheckResult("bank_evidence", False, "bank_amount_conflict", "Independent bank evidence amount conflicts with the screenshot claim."))
    elif evidence.receiver_upi_id != expected_receiver_upi_id:
        checks.append(CheckResult("bank_evidence", False, "bank_payee_conflict", "Independent bank evidence receiver conflicts with the configured group payee."))
    elif claim.member_id != evidence.payer_member_id:
        checks.append(CheckResult("bank_evidence", False, "bank_member_conflict", "Independent bank evidence belongs to a different member."))
    else:
        checks.append(CheckResult("bank_evidence", True, "evidence_matches", "Independent bank evidence matches the claim."))

    if not valid_utr or used is None:
        checks.append(CheckResult("utr_uniqueness", False, "cannot_check_utr_uniqueness", "UTR uniqueness requires a valid reference and an available used-UTR registry."))
    elif claim.utr in used:
        checks.append(CheckResult("utr_uniqueness", False, "duplicate_utr", "Transaction reference was already used in the group ledger."))
    else:
        checks.append(CheckResult("utr_uniqueness", True, "unique_utr", "Transaction reference is not already used."))

    if claim.image_sha256 is None:
        checks.append(CheckResult("image_uniqueness", False, "missing_image_hash", "Image hash is unavailable, so screenshot reuse cannot be checked."))
    elif not isinstance(claim.image_sha256, str) or not SHA256_PATTERN.fullmatch(claim.image_sha256):
        checks.append(CheckResult("image_uniqueness", False, "invalid_image_hash", "Image hash is not a valid SHA-256 digest."))
    elif image_hash_registry is None:
        checks.append(CheckResult("image_uniqueness", False, "cannot_check_image_uniqueness", "Screenshot reuse cannot be checked without an image hash registry."))
    elif image_hash_registry.contains(claim.image_sha256):
        checks.append(CheckResult("image_uniqueness", False, "duplicate_image", "Screenshot image was already submitted."))
    else:
        checks.append(CheckResult("image_uniqueness", True, "unique_image", "Screenshot image hash is not already recorded."))

    flags = tuple(flag.strip() for flag in claim.integrity_flags if flag.strip())
    if flags:
        checks.append(CheckResult("image_integrity", False, "suspicious_image", f"Screenshot integrity indicators require review: {', '.join(flags)}."))
    else:
        checks.append(CheckResult("image_integrity", True, "no_integrity_flags", "No screenshot integrity indicators were supplied."))
    return PaymentCheckReport(claim, expected_amount_paise, expected_receiver_upi_id, evidence, tuple(checks))
