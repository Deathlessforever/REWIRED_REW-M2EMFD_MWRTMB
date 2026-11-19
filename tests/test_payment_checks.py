from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.payment_checks import (
    ExtractedPaymentClaim,
    InMemoryImageHashRegistry,
    load_bank_evidence,
    validate_payment_claim,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVIDENCE = load_bank_evidence(DATA / "bank.csv")
GROUP = json.loads((DATA / "demo_chit.json").read_text(encoding="utf-8"))["group"]
SCENARIOS = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
SCHEMA = json.loads((ROOT / "contracts" / "schemas.json").read_text(encoding="utf-8"))


def claim(**changes):
    values = {
        "member_id": "member-01",
        "utr": "845270310001",
        "amount_paise": 500000,
        "receiver_upi_id": "saanvi-circle@demo.invalid",
        "image_sha256": "a" * 64,
        "integrity_flags": (),
    }
    return ExtractedPaymentClaim(**(values | changes))


def report(payment_claim, **changes):
    changes.setdefault("used_utrs", ())
    changes.setdefault("image_hash_registry", InMemoryImageHashRegistry())
    return validate_payment_claim(
        payment_claim,
        expected_amount_paise=500000,
        expected_receiver_upi_id=GROUP["group_upi_id"],
        evidence_by_utr=EVIDENCE,
        **changes,
    )


def codes(result):
    return {check.name: check.code for check in result.checks}


def test_valid_claim_matches_every_deterministic_check_but_is_not_a_payment_decision():
    result = report(claim())
    assert result.passed
    assert result.evidence is not None
    assert codes(result)["bank_evidence"] == "evidence_matches"
    assert not hasattr(result, "status")


@pytest.mark.parametrize(
    ("payment_claim", "check_name", "expected_code"),
    [
        (claim(utr="123"), "utr_format", "invalid_utr"),
        (claim(utr=None), "utr_format", "missing_utr"),
        (claim(amount_paise=499999), "expected_amount", "wrong_amount"),
        (claim(amount_paise=None), "expected_amount", "missing_or_invalid_amount"),
        (claim(receiver_upi_id="other@demo.invalid"), "payee", "wrong_payee"),
        (claim(receiver_upi_id=None), "payee", "missing_payee"),
        (claim(utr="845270319999"), "bank_evidence", "utr_not_in_bank_csv"),
        (claim(member_id="member-02"), "bank_evidence", "bank_member_conflict"),
        (claim(image_sha256="bad"), "image_uniqueness", "invalid_image_hash"),
        (claim(image_sha256=None), "image_uniqueness", "missing_image_hash"),
        (claim(integrity_flags=("metadata conflict",)), "image_integrity", "suspicious_image"),
    ],
)
def test_each_input_validation_check_has_a_clear_failure_reason(payment_claim, check_name, expected_code):
    result = report(payment_claim)
    check = result.by_name(check_name)
    assert not check.passed
    assert check.code == expected_code
    assert check.reason


def test_used_utr_and_previously_seen_image_are_rejected_by_their_independent_checks():
    registry = InMemoryImageHashRegistry(["a" * 64])
    result = report(claim(), used_utrs=["845270310001"], image_hash_registry=registry)
    assert codes(result)["utr_uniqueness"] == "duplicate_utr"
    assert codes(result)["image_uniqueness"] == "duplicate_image"


def test_conflicting_bank_amount_is_detected_even_when_claim_matches_expected_amount():
    conflicting_evidence = dict(EVIDENCE)
    original = conflicting_evidence["845270310001"]
    conflicting_evidence[original.utr] = replace(original, amount_paise=499999)
    result = validate_payment_claim(claim(), expected_amount_paise=500000, expected_receiver_upi_id=GROUP["group_upi_id"], evidence_by_utr=conflicting_evidence)
    assert codes(result)["bank_evidence"] == "bank_amount_conflict"


def test_untagged_bank_amount_is_not_accepted_as_independent_evidence():
    untagged_evidence = dict(EVIDENCE)
    original = untagged_evidence["845270310001"]
    untagged_evidence[original.utr] = replace(original, amount_tag="")
    result = validate_payment_claim(claim(), expected_amount_paise=500000, expected_receiver_upi_id=GROUP["group_upi_id"], evidence_by_utr=untagged_evidence)
    assert codes(result)["bank_evidence"] == "bank_missing_amount_tag"


def test_missing_duplicate_check_sources_fail_closed():
    result = validate_payment_claim(claim(), expected_amount_paise=500000,
                                    expected_receiver_upi_id=GROUP["group_upi_id"], evidence_by_utr=EVIDENCE)
    assert not result.passed
    assert codes(result)["utr_uniqueness"] == "cannot_check_utr_uniqueness"
    assert codes(result)["image_uniqueness"] == "cannot_check_image_uniqueness"


def test_evidence_mapping_cannot_substitute_a_different_utr():
    evidence = dict(EVIDENCE)
    evidence["845270310001"] = replace(evidence["845270310001"], utr="123456789012")
    result = validate_payment_claim(claim(), expected_amount_paise=500000,
                                    expected_receiver_upi_id=GROUP["group_upi_id"], evidence_by_utr=evidence,
                                    used_utrs=(), image_hash_registry=InMemoryImageHashRegistry())
    assert codes(result)["bank_evidence"] == "bank_reference_conflict"
    assert not result.passed


@pytest.mark.parametrize("bad_utr", [123456789012, "１２３４５６７８９０１２"])
def test_non_string_and_non_ascii_utr_fail_closed(bad_utr):
    result = report(claim(utr=bad_utr))
    assert codes(result)["utr_format"] == "invalid_utr"
    assert not result.passed


def test_boolean_amounts_and_non_string_hash_fail_closed():
    result = report(claim(amount_paise=True, image_sha256=123))
    assert codes(result)["expected_amount"] == "missing_or_invalid_amount"
    assert codes(result)["image_uniqueness"] == "invalid_image_hash"
    with pytest.raises(ValueError):
        validate_payment_claim(claim(), expected_amount_paise=True,
                               expected_receiver_upi_id=GROUP["group_upi_id"], evidence_by_utr=EVIDENCE)


def test_t06_planted_scenarios_produce_their_expected_deterministic_checks():
    expectations = {
        "genuine_on_time": {"bank_evidence": "evidence_matches", "utr_uniqueness": "unique_utr"},
        "reused_utr": {"utr_uniqueness": "duplicate_utr"},
        "fake_utr_not_in_csv": {"bank_evidence": "utr_not_in_bank_csv"},
        "wrong_amount": {"expected_amount": "wrong_amount", "bank_evidence": "bank_amount_conflict"},
        "late_payer": {"bank_evidence": "evidence_matches"},
    }
    for scenario in SCENARIOS:
        raw_claim = scenario["claim"]
        payment_claim = claim(
            member_id=raw_claim["member_id"], utr=raw_claim["utr"], amount_paise=raw_claim["amount_paise"], receiver_upi_id=raw_claim["receiver_upi_id"],
            image_sha256=f"{len(scenario['id']):064x}",
        )
        used_utrs = [raw_claim["utr"]] if scenario["id"] == "reused_utr" else []
        result = report(payment_claim, used_utrs=used_utrs)
        for check_name, expected_code in expectations[scenario["id"]].items():
            assert codes(result)[check_name] == expected_code


def test_scenario_result_cards_still_validate_against_the_shared_t01_contract():
    validator = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/bubble"})
    for scenario in SCENARIOS:
        validator.validate(scenario["expected_result"]["bubble"])


def test_bad_csv_is_rejected_without_trusting_its_rows(tmp_path):
    source = tmp_path / "evidence.csv"
    source.write_text("utr,amount_paise,receiver_upi_id,payer_member_id,bank_status\nbad,500000,x,y,SETTLED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid UTR"):
        load_bank_evidence(source)
