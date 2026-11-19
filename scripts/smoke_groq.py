"""Run one live Groq vision smoke check against a synthetic or masked image."""

import argparse
from pathlib import Path

import httpx

from backend.provider_smoke import ProviderSmokeError, run_groq_smoke


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, type=Path, help="Synthetic or masked PNG/JPG only")
    args = parser.parse_args()
    try:
        with httpx.Client() as client:
            result = run_groq_smoke(args.image, client=client)
    except ProviderSmokeError as error:
        print(f"Groq smoke check failed: {error}")
        return 1
    print(result.as_json())
    print(f"under_10_seconds={result.response_time_ms < 10_000}")
    return 0 if result.response_time_ms < 10_000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
