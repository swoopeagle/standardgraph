"""Master eval runner — runs all automated checks in tiers and prints a summary.

Tiers
-----
  structural  Pure-SQL checks. No network. Fast (seconds). Always safe in CI.
  semantic    Embedding-based checks (need Ollama at localhost:11434). Minutes.
  llm         End-to-end checks that call the Claude API (need ANTHROPIC_API_KEY).

By default runs `structural` + `semantic` with the LLM judge OFF (deterministic
pass/fail only). Pass --judge to enable the LLM judge on the semantic tier, or
--tier llm / --tier all to include the end-to-end Claude checks.

Usage:
  uv run python scripts/eval/run_all.py                 # structural + semantic, no judge
  uv run python scripts/eval/run_all.py --tier structural
  uv run python scripts/eval/run_all.py --judge         # + LLM judge (remote)
  uv run python scripts/eval/run_all.py --local-judge   # judge via local Ollama
  uv run python scripts/eval/run_all.py --tier all      # include e2e Claude checks

Skips gemma_sampler (interactive/manual) — run that separately.
"""
import argparse
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.eval import (
    # structural (pure SQL)
    db_integrity, coverage, duplicates, crosswalk_quality,
    # semantic (Ollama embeddings; some accept a judge)
    search_quality, search_filter_tests, coverage_matrix, lookup_standard_tests,
    map_fallback_tests, subject_crosswalk_tests, crosswalk_semantic_tests,
    two_hop_bridge_tests, progression_coherence_tests, adversarial_tests,
    persona_tests,
    # llm (Claude API end-to-end)
    e2e_claude_test,
)

# tier -> [(label, module), ...]
TIERS: dict[str, list[tuple[str, object]]] = {
    "structural": [
        ("DB integrity",                      db_integrity),
        ("Coverage & known IDs",              coverage),
        ("Duplicate detection",               duplicates),
        ("Crosswalk quality",                 crosswalk_quality),
    ],
    "semantic": [
        ("Search quality (golden)",           search_quality),
        ("Search filter accuracy",            search_filter_tests),
        ("Coverage matrix (all systems)",     coverage_matrix),
        ("lookup_standard correctness",       lookup_standard_tests),
        ("map_standard fallback",             map_fallback_tests),
        ("Subject crosswalk routing",         subject_crosswalk_tests),
        ("Crosswalk semantic quality",        crosswalk_semantic_tests),
        ("Two-hop bridge mapping",            two_hop_bridge_tests),
        ("Progression coherence",             progression_coherence_tests),
        ("Adversarial robustness",            adversarial_tests),
        ("Persona scenarios",                 persona_tests),
    ],
    "llm": [
        ("E2E Claude tool-use",               e2e_claude_test),
    ],
}

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[90mSKIP\033[0m"


def _invoke(module, no_judge: bool, local_judge: bool) -> int:
    """Call module.main(), passing only the kwargs its signature accepts.

    Normalizes the return: modules that return None (e.g. e2e) are treated as
    rc 0 unless they raise.
    """
    sig = inspect.signature(module.main)
    kwargs = {}
    if "no_judge" in sig.parameters:
        kwargs["no_judge"] = no_judge
    if "local_judge" in sig.parameters:
        kwargs["local_judge"] = local_judge
    rc = module.main(**kwargs)
    return 0 if rc is None else int(rc)


def main() -> None:
    ap = argparse.ArgumentParser(description="StandardGraph evaluation suite")
    ap.add_argument(
        "--tier", default="default",
        choices=["structural", "semantic", "llm", "default", "all"],
        help="Which tier(s) to run. 'default' = structural+semantic (no e2e). "
             "'all' = every tier.",
    )
    ap.add_argument("--judge", action="store_true",
                    help="Enable the LLM judge on semantic checks (remote).")
    ap.add_argument("--local-judge", action="store_true",
                    help="Use the local Ollama judge instead of the remote one.")
    args = ap.parse_args()

    if args.tier == "default":
        tiers = ["structural", "semantic"]
    elif args.tier == "all":
        tiers = ["structural", "semantic", "llm"]
    else:
        tiers = [args.tier]

    # Judge defaults OFF so the suite is deterministic unless asked otherwise.
    no_judge = not (args.judge or args.local_judge)

    print("\n" + "=" * 60)
    print("  StandardGraph Evaluation Suite")
    print(f"  tiers={', '.join(tiers)}   judge={'off' if no_judge else ('local' if args.local_judge else 'remote')}")
    print("=" * 60)

    results: list[tuple[str, str, int]] = []   # (tier, label, rc)
    for tier in tiers:
        for label, module in TIERS[tier]:
            print(f"\n{'━'*60}")
            print(f"  [{tier}] {label}")
            print(f"{'━'*60}")
            try:
                rc = _invoke(module, no_judge=no_judge, local_judge=args.local_judge)
            except Exception as e:
                print(f"  ERROR: {e}")
                rc = 1
            results.append((tier, label, rc))

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    current = None
    for tier, label, rc in results:
        if tier != current:
            print(f"\n  {tier.upper()}")
            current = tier
        tag = OK if rc == 0 else FAIL
        print(f"    [{tag}] {label}")

    failed = sum(1 for _, _, rc in results if rc != 0)
    print(f"\n  {failed}/{len(results)} checks failed\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
