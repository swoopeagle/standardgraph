"""Fetch and ingest Social Studies standards for all US states via CSP.

System IDs: {abbrev}-ss  e.g. tx-ss, ca-ss
Subject: social-studies
Crosswalk hub: c3
"""
from ingestion.shared.csp_state_fetcher import SubjectConfig, fetch_all_states

CONFIG = SubjectConfig(
    include_kw=(
        "social studies", "history", "civics", "geography",
        "economics", "government", "c3", "civic",
    ),
    exclude_kw=(
        "english", "language arts", "math", "science", "reading",
        "bilingual", "español", "spanish", "alternate", "modified",
        "access", "vaap", "computer",
    ),
    system_suffix="-ss",
    subject_value="social-studies",
    raw_subdir="ss_states",
    source_label="State Social Studies Standards",
)


def main() -> None:
    fetch_all_states(CONFIG)


if __name__ == "__main__":
    main()
