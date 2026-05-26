import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup


GLOBAL_NOISE_PATTERNS = [
    "cookie",
    "consent",
    "privacy",
    "datenschutz",
    "impressum",
    "breadcrumb",
    "sidebar",
    "footer",
    "header",
    "topbar",
    "toolbar",
    "social",
    "share",
    "follow",
    "newsletter",
    "popup",
    "modal",
    "banner",
    "promo",
    "advert",
]

GLOBAL_NOISE_PHRASES = [
    "accept all",
    "allow all",
    "cookie settings",
    "privacy settings",
    "share this page",
    "follow us",
    "contact us",
    "back to top",
    "skip to content",
    "hauptnavigation",
    "hauptmenü",
    "schnellzugriff",
    "diese seite teilen",
    "ihre cookie-einstellungen",
    "technisch notwendig",
    "bei facebook teilen",
    "bei linkedin teilen",
    "bei pinterest teilen",
    "bei xing teilen",
    "bei whatsapp teilen",
]

DEFAULT_MAIN_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    "#main",
    "#content",
    "#main-content",
    ".main-content",
    ".content",
    ".page-content",
    ".article-content",
]


def normalize_whitespace(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _link_density(tag) -> float:
    text = normalize_whitespace(tag.get_text(" ", strip=True))
    total_words = _word_count(text)
    if total_words == 0:
        return 1.0
    link_text = " ".join(a.get_text(" ", strip=True) for a in tag.find_all("a"))
    link_words = _word_count(link_text)
    return link_words / max(total_words, 1)


def _noise_phrase_hits(text: str, site_noise_phrases: Optional[List[str]] = None) -> int:
    lower = normalize_whitespace(text).lower()
    phrases = list(GLOBAL_NOISE_PHRASES)
    if site_noise_phrases:
        phrases.extend([p.lower() for p in site_noise_phrases if p])
    return sum(1 for phrase in phrases if phrase in lower)


def _attr_noise_hits(tag, site_noise_patterns: Optional[List[str]] = None) -> int:
    patterns = list(GLOBAL_NOISE_PATTERNS)
    if site_noise_patterns:
        patterns.extend([p.lower() for p in site_noise_patterns if p])
    haystacks: List[str] = [tag.name.lower()]
    for attr in ("id", "class", "aria-label", "data-testid", "data-role"):
        value = tag.get(attr)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        haystacks.extend(str(v).lower() for v in values)
    joined = " ".join(haystacks)
    return sum(1 for pattern in patterns if pattern in joined)


def _duplicate_line_ratio(text: str) -> float:
    lines = [normalize_whitespace(line) for line in (text or "").splitlines() if normalize_whitespace(line)]
    if not lines:
        return 0.0
    unique_lines = len(set(lines))
    return max(0.0, 1.0 - (unique_lines / len(lines)))


def _boilerplate_ratio(text: str, site_noise_phrases: Optional[List[str]] = None) -> float:
    lines = [normalize_whitespace(line) for line in (text or "").splitlines() if normalize_whitespace(line)]
    if not lines:
        return 0.0
    noisy = 0
    for line in lines:
        if _noise_phrase_hits(line, site_noise_phrases):
            noisy += 1
    return noisy / len(lines)


def drop_boilerplate_sections(
    soup: BeautifulSoup,
    max_link_density: float = 0.4,
    max_link_density_words: int = 200,
    site_noise_phrases: Optional[List[str]] = None,
    site_noise_patterns: Optional[List[str]] = None,
    preserve_root: bool = False,
) -> Tuple[BeautifulSoup, List[str]]:
    dropped_sections: List[str] = []
    root_tag = soup.find(True) if preserve_root else None

    for tag in soup.find_all(["header", "footer", "nav", "aside", "form", "script", "style", "noscript"]):
        if preserve_root and root_tag is not None and tag is root_tag:
            continue
        dropped_sections.append(f"removed_tag:{tag.name}")
        tag.decompose()

    def is_noisy(tag) -> bool:
        if tag.name in ("html", "body"):
            return False
        text = normalize_whitespace(tag.get_text(" ", strip=True))
        if not text:
            return True
        total_words = _word_count(text)
        if total_words == 0:
            return True
        link_density = _link_density(tag)
        attr_hits = _attr_noise_hits(tag, site_noise_patterns)
        phrase_hits = _noise_phrase_hits(text, site_noise_phrases)
        link_list = len(tag.find_all("a")) >= 5 and link_density > 0.6
        short_noisy_block = total_words <= max_link_density_words and link_density >= max_link_density
        return link_list or short_noisy_block or attr_hits >= 2 or phrase_hits >= 2

    for tag in list(soup.find_all(True)):
        if preserve_root and root_tag is not None and tag is root_tag:
            continue
        if is_noisy(tag):
            dropped_sections.append(f"removed_block:{tag.name}")
            tag.decompose()

    return soup, dropped_sections


def score_content_candidates(
    soup: BeautifulSoup,
    site_selectors: Optional[List[str]] = None,
    site_noise_phrases: Optional[List[str]] = None,
    site_noise_patterns: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    selectors = list(DEFAULT_MAIN_SELECTORS)
    if site_selectors:
        selectors = [selector for selector in site_selectors if selector] + selectors

    seen = set()
    candidates = []

    for selector in selectors:
        try:
            for tag in soup.select(selector):
                if id(tag) not in seen:
                    seen.add(id(tag))
                    candidates.append(tag)
        except Exception:
            continue

    structural_tags = soup.find_all(["main", "article", "section", "div"])
    for tag in structural_tags:
        text = normalize_whitespace(tag.get_text(" ", strip=True))
        if _word_count(text) >= 80 and id(tag) not in seen:
            seen.add(id(tag))
            candidates.append(tag)

    scored: List[Dict[str, Any]] = []
    for tag in candidates:
        text = normalize_whitespace(tag.get_text("\n", strip=True))
        word_count = _word_count(text)
        if word_count < 20:
            continue
        link_density = _link_density(tag)
        headings = len(tag.find_all(["h1", "h2", "h3", "h4"]))
        paragraphs = len(tag.find_all("p"))
        lists = len(tag.find_all(["ul", "ol"]))
        attr_hits = _attr_noise_hits(tag, site_noise_patterns)
        phrase_hits = _noise_phrase_hits(text, site_noise_phrases)
        duplicate_ratio = _duplicate_line_ratio(text)
        boilerplate_ratio = _boilerplate_ratio(text, site_noise_phrases)
        score = 0.0
        score += min(word_count / 40.0, 18.0)
        score += headings * 2.5
        score += paragraphs * 1.2
        score += lists * 1.5
        if tag.name in ("main", "article"):
            score += 10
        elif tag.name == "section":
            score += 4
        if tag.get("role") and str(tag.get("role")).lower() == "main":
            score += 6
        if tag.get("id") in {"main", "content", "main-content"}:
            score += 5
        tag_classes = [str(c).lower() for c in (tag.get("class") or [])]
        if any(cls in {"content", "page-content", "main-content", "article-content"} for cls in tag_classes):
            score += 4
        if tag.name == "div":
            score -= 2
        score -= link_density * 25
        score -= attr_hits * 5
        score -= phrase_hits * 4
        score -= duplicate_ratio * 10
        score -= boilerplate_ratio * 12
        scored.append(
            {
                "tag": tag,
                "score": score,
                "word_count": word_count,
                "link_density": link_density,
                "heading_count": headings,
                "paragraph_count": paragraphs,
                "list_count": lists,
                "duplicate_ratio": duplicate_ratio,
                "boilerplate_ratio": boilerplate_ratio,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def extract_main_content_html(
    html: str,
    max_link_density: float = 0.4,
    max_link_density_words: int = 200,
    site_selectors: Optional[List[str]] = None,
    site_noise_phrases: Optional[List[str]] = None,
    site_noise_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    scored = score_content_candidates(
        soup,
        site_selectors=site_selectors,
        site_noise_phrases=site_noise_phrases,
        site_noise_patterns=site_noise_patterns,
    )
    candidate_details = [
        {
            "score": round(item["score"], 2),
            "tag_name": item["tag"].name,
            "tag_id": item["tag"].get("id"),
            "tag_class": [str(c) for c in (item["tag"].get("class") or [])][:6],
            "word_count": item["word_count"],
            "link_density": round(item["link_density"], 3),
            "heading_count": item["heading_count"],
            "paragraph_count": item["paragraph_count"],
            "duplicate_ratio": round(item["duplicate_ratio"], 3),
            "boilerplate_ratio": round(item["boilerplate_ratio"], 3),
        }
        for item in scored[:3]
    ]

    selected_html = None
    selected_text = ""
    dropped_sections: List[str] = []
    selected_via = "body_fallback"
    selected_score = 0.0

    candidate_pool = scored or [{"tag": (soup.body or soup), "score": 0.0}]
    for index, item in enumerate(candidate_pool[:5]):
        candidate_tag = item["tag"]
        candidate_html = BeautifulSoup(str(candidate_tag), "html.parser")
        candidate_html, candidate_dropped_sections = drop_boilerplate_sections(
            candidate_html,
            max_link_density=max_link_density,
            max_link_density_words=max_link_density_words,
            site_noise_phrases=site_noise_phrases,
            site_noise_patterns=site_noise_patterns,
            preserve_root=True,
        )
        candidate_text = normalize_whitespace(candidate_html.get_text("\n", strip=True))
        if candidate_text:
            selected_html = candidate_html
            selected_text = candidate_text
            dropped_sections = candidate_dropped_sections
            selected_score = round(item["score"], 2)
            selected_via = "candidate_scoring" if scored else "body_fallback"
            if index > 0:
                selected_via = f"{selected_via}_fallback_{index + 1}"
            break

    if selected_html is None:
        selected_html = BeautifulSoup(str(soup.body or soup), "html.parser")
        selected_html, dropped_sections = drop_boilerplate_sections(
            selected_html,
            max_link_density=max_link_density,
            max_link_density_words=max_link_density_words,
            site_noise_phrases=site_noise_phrases,
            site_noise_patterns=site_noise_patterns,
            preserve_root=True,
        )
        selected_text = normalize_whitespace(selected_html.get_text("\n", strip=True))

    return {
        "html": str(selected_html),
        "text": selected_text,
        "candidate_details": candidate_details,
        "dropped_sections": dropped_sections,
        "selected_via": selected_via,
        "selected_score": selected_score,
    }


def clean_html_for_markdown(
    html: str,
    max_link_density: float = 0.4,
    max_link_density_words: int = 200,
    site_selectors: Optional[List[str]] = None,
    site_noise_phrases: Optional[List[str]] = None,
    site_noise_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Select and clean the most content-rich portion of the page before markdown conversion.
    """
    return extract_main_content_html(
        html,
        max_link_density=max_link_density,
        max_link_density_words=max_link_density_words,
        site_selectors=site_selectors,
        site_noise_phrases=site_noise_phrases,
        site_noise_patterns=site_noise_patterns,
    )


def filter_markdown_lines(markdown: str, site_noise_phrases: Optional[List[str]] = None) -> str:
    """Remove leftover navigation/cookie/share lines after markdown conversion."""
    drop_phrases = list(GLOBAL_NOISE_PHRASES)
    if site_noise_phrases:
        drop_phrases.extend([p.lower() for p in site_noise_phrases if p])
    kept = []
    for line in markdown.splitlines():
        stripped = normalize_whitespace(line)
        if not stripped:
            continue
        lower = stripped.lower()
        if any(p in lower for p in drop_phrases):
            continue
        kept.append(stripped)
    normalized = "\n".join(kept)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def finalize_markdown_content(
    markdown: str,
    site_noise_phrases: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """Final cleanup pass before persisting markdown output."""
    warnings: List[str] = []
    cleaned: List[str] = []
    seen_headings = set()
    drop_phrases = list(GLOBAL_NOISE_PHRASES)
    if site_noise_phrases:
        drop_phrases.extend([p.lower() for p in site_noise_phrases if p])

    def is_link_only_line(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if re.fullmatch(r"[\-\*\d\.\)\s]*\[.+?\]\(.+?\)", stripped):
            return True
        if re.fullmatch(r"[\-\*\d\.\)\s]*https?://\S+", stripped):
            return True
        return False

    def is_content_rich_list_item(text: str) -> bool:
        if not re.match(r"^([-\*\+]\s+|\d+\.\s+)", text):
            return False
        body = re.sub(r"^([-\*\+]\s+|\d+\.\s+)", "", text).strip()
        return _word_count(body) >= 4

    recent_link_only_count = 0
    for raw_line in markdown.splitlines():
        line = normalize_whitespace(raw_line)
        if not line:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            recent_link_only_count = 0
            continue

        lower = line.lower()
        if any(phrase in lower for phrase in drop_phrases):
            warnings.append("removed_markdown_noise_line")
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            heading_key = heading_match.group(2).strip().lower()
            if heading_key in seen_headings:
                warnings.append("removed_duplicate_heading")
                continue
            seen_headings.add(heading_key)
            recent_link_only_count = 0
            cleaned.append(line)
            continue

        if is_link_only_line(line):
            recent_link_only_count += 1
            if recent_link_only_count > 1:
                warnings.append("removed_repetitive_link_only_line")
                continue
            cleaned.append(line)
            continue
        recent_link_only_count = 0

        if _word_count(line) <= 1 and not re.match(r"^([-\*\+]\s+|\d+\.\s+)", line):
            warnings.append("removed_tiny_orphan_line")
            continue

        if re.match(r"^([-\*\+]\s+|\d+\.\s+)", line) and not is_content_rich_list_item(line):
            warnings.append("removed_thin_list_item")
            continue

        if line.startswith("|") and line.endswith("|") and _word_count(line) < 3:
            warnings.append("removed_thin_table_row")
            continue

        cleaned.append(line)

    output = "\n".join(cleaned)
    output = re.sub(r"\n{3,}", "\n\n", output).strip()
    return output, sorted(set(warnings))
