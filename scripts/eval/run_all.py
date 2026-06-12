"""Master eval runner — runs all automated checks and prints a summary.

Usage: uv run python scripts/eval/run_all.py
Skips the gemma_sampler (interactive/manual) — run that separately.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.eval import coverage, duplicates, crosswalk_quality, search_quality

CHECKS = [
    ("Coverage & known IDs",    coverage),
    ("Duplicate detection",     duplicates),
    ("Crosswalk quality",       crosswalk_quality),
    ("Search quality (golden)", search_quality),
]

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"


def main() -> None:
    print("\n" + "=" * 60)
    print("  StandardGraph Evaluation Suite")
    print("=" * 60)

    results = []
    for label, module in CHECKS:
        print(f"\n{'━'*60}")
        print(f"  {label}")
        print(f"{'━'*60}")
        try:
            rc = module.main()
        except Exception as e:
            print(f"  ERROR: {e}")
            rc = 1
        results.append((label, rc))

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    for label, rc in results:
        tag = OK if rc == 0 else FAIL
        print(f"  [{tag}] {label}")

    failed = sum(1 for _, rc in results if rc != 0)
    print(f"\n  {failed}/{len(results)} checks failed")
    print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
