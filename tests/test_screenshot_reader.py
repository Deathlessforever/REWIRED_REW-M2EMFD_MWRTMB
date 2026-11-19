from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from fastapi.testclient import TestClient

from backend.screenshot_reader import ScreenshotReaderQueue, needs_review_response, read_uploaded_screenshot
from backend.provider_smoke import ProviderSmokeError
from backend.main import app


ROOT = Path(__file__).resolve().parents[1]


def png() -> bytes:
    return b"\x89PNG\r\n\x1a\nsynthetic"


def zipped(text: str) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("result.md", text)
    return result.getvalue()


def test_sarvam_claim_is_nullable_and_maps_only_to_needs_review(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    def handler(request):
        if request.url.path.endswith("/parse"): return httpx.Response(201, json={"job_id": "job"})
        if request.url.path.endswith("/status"): return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/download-url"): return httpx.Response(200, json={"method": "GET", "url": "https://download.test/result.zip", "headers": {}})
        return httpx.Response(200, content=zipped("Paid ₹4,500 UTR 123456789012 to demo@upi using GPay"))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        claim = read_uploaded_screenshot("synthetic.png", png(), client)
    assert claim.utr == "123456789012" and claim.amount_paise == 450000
    assert claim.transaction_date is None and claim.confidence is None
    response = needs_review_response(claim)
    assert response["bubbles"][1]["status"] == "needs_review"
    schema = __import__("json").loads((ROOT / "contracts" / "schemas.json").read_text())
    Draft202012Validator({**schema, "$ref": "#/$defs/message_response"}).validate(response)


@pytest.mark.parametrize("name", ["bad.gif", "bad.txt"])
def test_bad_upload_extensions_are_rejected(monkeypatch, name):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    with pytest.raises(ProviderSmokeError, match="Only PNG"):
        read_uploaded_screenshot(name, png(), httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail())))


def test_reader_queue_supports_multiple_claim_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    image = tmp_path / "synthetic.png"; image.write_bytes(png())
    def handler(request):
        if request.url.path.endswith("/parse"): return httpx.Response(201, json={"job_id": "job"})
        if request.url.path.endswith("/status"): return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/download-url"): return httpx.Response(200, json={"method": "GET", "url": "https://download.test/result.zip", "headers": {}})
        return httpx.Response(200, content=zipped("UTR 123456789012"))
    queue = ScreenshotReaderQueue(); client = httpx.Client(transport=httpx.MockTransport(handler))
    try: assert queue.submit(image, client).result().utr == "123456789012"
    finally: queue.shutdown(); client.close()


def test_ten_synthetic_screenshots_are_submitted_as_unverified_claims(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    screenshot_paths = sorted((ROOT / "tests" / "fixtures" / "payment_screenshots").glob("*/*/*.png"))[:10]
    assert len(screenshot_paths) == 10

    def handler(request):
        if request.url.path.endswith("/parse"): return httpx.Response(201, json={"job_id": "job"})
        if request.url.path.endswith("/status"): return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/download-url"): return httpx.Response(200, json={"method": "GET", "url": "https://download.test/result.zip", "headers": {}})
        return httpx.Response(200, content=zipped("Payment completed"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        claims = [read_uploaded_screenshot(path.name, path.read_bytes(), client) for path in screenshot_paths]
    assert all(claim.utr is None and claim.amount_paise is None for claim in claims)


def test_message_endpoint_never_exposes_raw_ocr_or_marks_a_screenshot_verified(monkeypatch, tmp_path):
    monkeypatch.setenv("CHITMIRROR_DATABASE", str(tmp_path / "reader-test.db"))
    monkeypatch.setattr("backend.main.read_uploaded_screenshot", lambda *_: __import__("backend.screenshot_reader", fromlist=["ScreenshotClaim"]).ScreenshotClaim(
        "123456789012", 450000, "demo@upi", "completed", None, None, "GPay", None
    ))
    with TestClient(app) as client:
        response = client.post("/message", data={"sender": "member-01", "text": ""}, files={"image": ("claim.png", png(), "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert body["bubbles"][1]["status"] == "needs_review"
    assert "transaction_status" not in str(body)
