from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.provider_smoke import (
    ProviderSmokeError,
    image_media_type,
    run_groq_smoke,
    run_sarvam_smoke,
)


def write_image(path: Path, suffix: str = ".png") -> Path:
    image = path / f"synthetic{suffix}"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic" if suffix == ".png" else b"\xff\xd8\xff\xe0synthetic")
    return image


def output_zip(text: str) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("synthetic-payment.md", text)
        archive.writestr("metadata/page_001.json", "{}")
    return result.getvalue()


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sarvam_submits_polls_downloads_and_extracts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    image = write_image(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/parse"):
            assert request.headers["api-subscription-key"] == "test-only"
            assert b"language" in request.content and b"en-IN" in request.content
            return httpx.Response(201, json={"job_id": "job-synthetic"})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "pending" if len([r for r in requests if r.url.path.endswith('/status')]) == 1 else "completed"})
        if request.url.path.endswith("/download-url"):
            return httpx.Response(200, json={"method": "GET", "url": "https://download.synthetic/result.zip", "headers": {}})
        if request.url.host == "download.synthetic":
            return httpx.Response(200, content=output_zip("PhonePe completed ₹4,450.07 UTR 123456789012 to demo.chit@upi"))
        raise AssertionError(request.url)

    moments = iter([0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    result = run_sarvam_smoke(image, client=client_for(handler), now=lambda: next(moments), sleep=lambda _: None)
    assert result.provider == "sarvam"
    assert result.utr == "123456789012"
    assert result.amount_paise == 445007
    assert result.payee == "demo.chit@upi"
    assert result.transaction_status == "completed"
    assert result.payment_application == "PhonePe"
    assert any(request.url.path.endswith("/download-url") for request in requests)


def test_sarvam_handles_rate_limits_failed_jobs_timeouts_and_bad_zip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    image = write_image(tmp_path)
    with pytest.raises(ProviderSmokeError, match="rate limited"):
        run_sarvam_smoke(image, client=client_for(lambda _: httpx.Response(429)), now=lambda: 0)

    def failed_job(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"job_id": "job"}) if request.url.path.endswith("/parse") else httpx.Response(200, json={"status": "failed"})

    with pytest.raises(ProviderSmokeError, match="did not complete"):
        run_sarvam_smoke(image, client=client_for(failed_job), now=lambda: 0)

    def corrupt_download(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/parse"):
            return httpx.Response(201, json={"job_id": "job"})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/download-url"):
            return httpx.Response(200, json={"method": "GET", "url": "https://download.synthetic/bad.zip", "headers": {}})
        return httpx.Response(200, content=b"not a zip")

    with pytest.raises(ProviderSmokeError, match="valid ZIP"):
        run_sarvam_smoke(image, client=client_for(corrupt_download), now=lambda: 0)


def test_sarvam_handles_network_timeouts_and_malformed_provider_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SARVAM_API_KEY", "test-only")
    image = write_image(tmp_path)
    with pytest.raises(ProviderSmokeError, match="timed out"):
        run_sarvam_smoke(image, client=client_for(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("slow"))))
    with pytest.raises(ProviderSmokeError, match="malformed response"):
        run_sarvam_smoke(image, client=client_for(lambda _: httpx.Response(201, content=b"{")))


def test_groq_sends_png_and_extracts_structured_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    image = write_image(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.groq.com/openai/v1/chat/completions")
        assert request.headers["authorization"] == "Bearer test-only"
        payload = json.loads(request.content)
        assert payload["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "utr": "123456789012", "amount": "4,450.07", "payee": "demo.chit@upi",
            "transaction_status": "success", "transaction_date": "2026-11-05",
            "transaction_time": "10:15:00", "payment_application": "GPay",
        })}}]})

    moments = iter([0.0, 0.3])
    result = run_groq_smoke(image, client=client_for(handler), now=lambda: next(moments))
    assert result.provider == "groq"
    assert result.utr == "123456789012"
    assert result.amount_paise == 445007
    assert result.transaction_date == "2026-11-05"
    assert result.transaction_time == "10:15:00"


@pytest.mark.parametrize("suffix", [".png", ".jpg"])
def test_png_and_jpg_are_supported(tmp_path: Path, suffix: str):
    assert image_media_type(write_image(tmp_path, suffix)) in {"image/png", "image/jpeg"}


def test_missing_keys_corrupt_images_timeout_and_malformed_groq_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    image = write_image(tmp_path)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(ProviderSmokeError, match="SARVAM_API_KEY is missing"):
        run_sarvam_smoke(image, client=client_for(lambda _: pytest.fail("network called")))

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-image")
    with pytest.raises(ProviderSmokeError, match="invalid file signature"):
        image_media_type(corrupt)

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ProviderSmokeError, match="GROQ_API_KEY is missing"):
        run_groq_smoke(image, client=client_for(lambda _: pytest.fail("network called")))
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    with pytest.raises(ProviderSmokeError, match="rate limited"):
        run_groq_smoke(image, client=client_for(lambda _: httpx.Response(429)))
    with pytest.raises(ProviderSmokeError, match="timed out"):
        run_groq_smoke(image, client=client_for(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("slow"))))
    with pytest.raises(ProviderSmokeError, match="could not connect"):
        run_groq_smoke(image, client=client_for(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with pytest.raises(ProviderSmokeError, match="malformed JSON"):
        run_groq_smoke(image, client=client_for(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})))
    with pytest.raises(ProviderSmokeError, match="message content"):
        run_groq_smoke(image, client=client_for(lambda _: httpx.Response(200, json={"choices": []})))
