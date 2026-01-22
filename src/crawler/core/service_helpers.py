import re
from bs4 import BeautifulSoup


def clean_html_for_markdown(
    html: str,
    max_link_density: float = 0.4,
    max_link_density_words: int = 200
) -> str:
    """
    Clean raw HTML to retain only meaningful page content before markdown conversion.
    """
    soup = BeautifulSoup(html, "html.parser")
    # MAIN CONTENT ONLY REGION
    main_candidates = []
    main_candidates.extend(soup.find_all("main"))
    id_targets = {"main", "main-content", "content", "main-content-anchor"}
    main_candidates.extend(
        soup.find_all(lambda tag: tag.get("id") and str(tag.get("id")).lower() in id_targets)
    )
    main_candidates.extend(
        soup.find_all(lambda tag: tag.get("role") and str(tag.get("role")).lower() == "main")
    )
    if main_candidates:
        soup = BeautifulSoup(str(main_candidates[0]), "html.parser")
    # JUNK Tags removal + substrings like nav, menu, header etc
    for tag in soup.find_all(["header", "footer", "nav", "aside", "form", "script", "style", "noscript"]):
        tag.decompose()
    substrings = [
        "nav", "menu", "breadcrumb", "sidebar", "cookie", "consent", "cookie-banner",
        "footer", "header", "topbar", "toolbar", "hero-stage", "stage",
        "social", "share", "tracking", "banner", "popup"
    ]

    def has_bad_attr(tag):
        for attr in ("id", "class"):
            val = tag.get(attr)
            if not val:
                continue
            values = val if isinstance(val, list) else [val]
            for v in values:
                text_v = str(v).lower()
                if any(sub in text_v for sub in substrings):
                    return True
        return False

    for t in list(soup.find_all(has_bad_attr)):
        t.decompose()
    # HAWK-specific content removal (sitewide navigation, cookie, social, and footer blocks)
    navigation_keywords = [
        "hauptnavigation", "hauptmenü", "schnellzugriff",
        "diese seite teilen", "cookie-einstellungen", "ihre cookie-einstellungen",
        "technisch notwendig", "statistik", "externe medien", "sonstiges", "alle akzeptieren", "ablehnen",
        "impressum", "datenschutzerklärung", "datenschutzhinweis", "barrierefreiheit", "mittelverwendung",
        "meldestelle hinweisgeberschutzgesetz", "korruptionsprävention", "studienorganisation",
        "facebook", "linkedin", "pinterest", "xing", "whatsapp"
    ]

    def is_global_nav(tag):
        if tag.name not in ("section", "div"):
            return False
        text = (tag.get_text(" ", strip=True) or "").lower()
        return any(k in text for k in navigation_keywords)

    for t in list(soup.find_all(is_global_nav)):
        t.decompose()
    # Heuristic: remove sections that are mostly navigation/link lists
    for tag in list(soup.find_all(True)):
        if tag.name in ("html", "body"):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        total_words = len(re.findall(r"[A-Za-z0-9_]+", text))
        if total_words == 0 or total_words > max_link_density_words:
            continue
        link_text = " ".join(a.get_text(" ", strip=True) for a in tag.find_all("a"))
        link_words = len(re.findall(r"[A-Za-z0-9_]+", link_text))
        if link_words == 0:
            continue
        link_density = link_words / max(1, total_words)
        if link_density >= max_link_density:
            tag.decompose()
    return str(soup)


def filter_markdown_lines(markdown: str) -> str:
    """Remove leftover navigation/cookie/share lines after markdown conversion."""
    drop_phrases = [
        "hauptnavigation", "hauptmenü", "schnellzugriff",
        "cookie-einstellungen", "ihre cookie-einstellungen",
        "technisch notwendig", "statistik", "externe medien", "sonstiges",
        "bei facebook teilen", "bei linkedin teilen", "bei pinterest teilen",
        "bei xing teilen", "bei whatsapp teilen", "diese seite teilen"
    ]
    kept = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(p in lower for p in drop_phrases):
            continue
        kept.append(line)
    return "\n".join(kept)

