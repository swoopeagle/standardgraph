"""Fetch and ingest Computer Science standards for US states via CSP.

System IDs: {abbrev}-cs  e.g. tx-cs, ca-cs
Subject: cs
Crosswalk hub: csta
Coverage: 34/51 states (those with CS standards in CSP).
See docs/cs_coverage_gaps.md for the 17 missing states and fill-in plan.
"""
from ingestion.shared.csp_state_fetcher import SubjectConfig, fetch_all_states

CONFIG = SubjectConfig(
    include_kw=(
        "computer science", "computing", "digital literacy",
        "coding", "informatics", "computational thinking",
    ),
    exclude_kw=(
        "health", "family", "consumer", "agriculture",
        "alternate", "modified", "access", "vaap",
        "english", "math", "science", "social studies",
    ),
    system_suffix="-cs",
    subject_value="cs",
    raw_subdir="cs_states",
    source_label="State Computer Science Standards",
)


def main() -> None:
    fetch_all_states(CONFIG)


if __name__ == "__main__":
    main()
