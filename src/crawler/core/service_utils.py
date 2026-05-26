"""Compatibility exports for content quality helpers.

New code should import these helpers from
``hawki_crawler.crawler.parsing.content_quality``.
"""

from hawki_crawler.crawler.parsing.content_quality import (
    assess_content_quality,
    detect_language_confidence,
)

__all__ = ["assess_content_quality", "detect_language_confidence"]
