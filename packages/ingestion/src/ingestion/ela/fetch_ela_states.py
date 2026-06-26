"""Fetch and ingest ELA standards for all US states via commonstandardsproject.com.

System IDs: {abbrev}-ela  e.g. tx-ela, ca-ela
Subject: ela
Crosswalk hub: ccss-ela
"""
from ingestion.shared.csp_state_fetcher import SubjectConfig, fetch_all_states

CONFIG = SubjectConfig(
    include_kw=(
        "english language arts", "ela", "literacy", "reading", "writing",
        "language arts", "english/language",
    ),
    exclude_kw=(
        "bilingual", "español", "spanish", "français", "french",
        "alternate", "modified", "access", "vaap",
        "computer", "social studies", "science", "math",
    ),
    system_suffix="-ela",
    subject_value="ela",
    raw_subdir="ela_states",
    source_label="State ELA Standards",
)


def main() -> None:
    fetch_all_states(CONFIG)


if __name__ == "__main__":
    main()
