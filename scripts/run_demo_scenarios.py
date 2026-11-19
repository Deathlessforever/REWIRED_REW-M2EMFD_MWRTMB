"""Run and report the five planted synthetic payment scenarios."""

import sys
from pathlib import Path

# Running this file directly puts scripts/ rather than the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.demo import run_planted_scenarios


def main() -> int:
    try:
        results = run_planted_scenarios()
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}")
        return 1
    for result in results:
        print(f"PASS: {result['id']} → {result['result']['bubble']['status']}")
    print(f"PASS: {len(results)} synthetic scenarios match their expected result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
