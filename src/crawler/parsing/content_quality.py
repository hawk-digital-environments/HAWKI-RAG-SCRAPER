import re
from typing import Any, Dict, List, Optional


def detect_language_confidence(lang: Optional[str], markdown: str) -> float:
    if not markdown or not markdown.strip():
        return 0.0
    if not lang:
        return 0.25
    word_count = len(re.findall(r"\b\w+\b", markdown))
    if word_count >= 150:
        return 0.95
    if word_count >= 75:
        return 0.85
    if word_count >= 25:
        return 0.7
    return 0.55


def assess_content_quality(
    markdown: str,
    min_word_count: int,
    *,
    link_density: float = 0.0,
    heading_count: int = 0,
    paragraph_count: int = 0,
    duplicate_ratio: float = 0.0,
    boilerplate_ratio: float = 0.0,
    language_confidence: float = 0.0,
) -> Dict[str, Any]:
    """Assess extracted page content using text, structure, and noise signals."""
    word_count = len(re.findall(r"\b\w+\b", markdown, flags=re.UNICODE))
    score = 0.0
    score += min(word_count / 4.0, 45.0)
    score += min(heading_count * 3.0, 15.0)
    score += min(paragraph_count * 1.5, 15.0)
    score += max(0.0, (1.0 - min(link_density, 1.0))) * 12.0
    score += max(0.0, (1.0 - min(duplicate_ratio, 1.0))) * 8.0
    score += max(0.0, (1.0 - min(boilerplate_ratio, 1.0))) * 10.0
    score += max(0.0, min(language_confidence, 1.0)) * 10.0
    score = max(0.0, min(100.0, score))

    reasons: List[str] = []
    if min_word_count > 0 and word_count < min_word_count:
        reasons.append(f"word_count_below_{min_word_count}")
    if link_density > 0.6:
        reasons.append("high_link_density")
    if duplicate_ratio > 0.35:
        reasons.append("high_duplicate_ratio")
    if boilerplate_ratio > 0.3:
        reasons.append("high_boilerplate_ratio")
    if paragraph_count == 0 and word_count > 40:
        reasons.append("missing_paragraph_structure")

    quality_label = "high"
    if score < 80:
        quality_label = "medium"
    if score < 55:
        quality_label = "low"
    if score < 30:
        quality_label = "very_low"

    content_classification = "success"
    if word_count == 0:
        content_classification = "empty"
    elif score < 30:
        content_classification = "partial"
    elif score < 45:
        content_classification = "noisy"

    return {
        "score": round(score, 2),
        "quality_label": quality_label,
        "content_classification": content_classification,
        "is_low_quality": bool(reasons) or score < 45,
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "signals": {
            "word_count": word_count,
            "link_density": round(link_density, 4),
            "heading_count": heading_count,
            "paragraph_count": paragraph_count,
            "duplicate_ratio": round(duplicate_ratio, 4),
            "boilerplate_ratio": round(boilerplate_ratio, 4),
            "language_confidence": round(language_confidence, 4),
        },
    }
