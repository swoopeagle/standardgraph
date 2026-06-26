"""Shared utilities for PDF-based Gemma extraction fetchers."""
import re


def is_standards_page(text: str) -> bool:
    """Return False only for pages we are certain contain no standards.

    Conservative: only skips TOC pages (dot-leader pattern) and
    copyright/colophon pages. Everything else is sent to Gemma — a
    0-extraction result is cheaper than a missed standard.
    """
    # Table of contents: 5+ lines of "Heading ........ 12"
    if len(re.findall(r'\.{4,}\s*\d+', text)) >= 5:
        return False

    # Copyright / colophon page with no numbered items
    if (re.search(r'\b(isbn|copyright\s*©|all rights reserved)\b', text, re.IGNORECASE)
            and not re.search(r'^\s*\d+\.', text, re.MULTILINE)):
        return False

    return True
