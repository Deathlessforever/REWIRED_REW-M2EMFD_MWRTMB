"""Run and report the five planted synthetic payment scenarios."""

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
