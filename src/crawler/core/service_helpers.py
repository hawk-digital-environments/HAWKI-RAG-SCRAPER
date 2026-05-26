"""Compatibility exports for content parsing helpers.

New code should import these helpers from ``hawki_crawler.crawler.parsing.content_helpers``.
"""

from hawki_crawler.crawler.parsing.content_helpers import (
    DEFAULT_MAIN_SELECTORS,
    GLOBAL_NOISE_PATTERNS,
    GLOBAL_NOISE_PHRASES,
    clean_html_for_markdown,
    drop_boilerplate_sections,
    extract_main_content_html,
    filter_markdown_lines,
    finalize_markdown_content,
    normalize_whitespace,
    score_content_candidates,
)

__all__ = [
    "DEFAULT_MAIN_SELECTORS",
    "GLOBAL_NOISE_PATTERNS",
    "GLOBAL_NOISE_PHRASES",
    "clean_html_for_markdown",
    "drop_boilerplate_sections",
    "extract_main_content_html",
    "filter_markdown_lines",
    "finalize_markdown_content",
    "normalize_whitespace",
    "score_content_candidates",
]
