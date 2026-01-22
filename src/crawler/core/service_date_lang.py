from typing import Optional, Dict
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime


class ServiceDateLangMixin:
    def parse_date_string(self, date_str: str) -> Optional[str]:
        """Parse a free-form date string into ISO-8601 when possible."""
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            if dt:
                return dt.isoformat()
        except Exception:
            pass
        return None

    def extract_dates(self, html_content: str, soup: BeautifulSoup) -> Dict[str, Optional[str]]:
        """
        Extract published/updated dates from HTML.
        """
        # Priority: meta tags (og/article/date/lastmod variants), <time> tags, then elements with
        # date-like attributes or text
        published = None
        updated = None

        def pick(first: Optional[str], second: Optional[str]) -> Optional[str]:
            return first or second

        # Meta tags
        meta_tags = soup.find_all("meta")
        meta_map = {
            'article:published_time': 'published',
            'article:modified_time': 'updated',
            'og:updated_time': 'updated',
            'og:published_time': 'published',
            'date': 'published',
            'lastmod': 'updated'
        }
        for tag in meta_tags:
            prop = tag.get('property') or tag.get('name')
            content = tag.get('content')
            if not prop or not content:
                continue
            prop = prop.lower()
            target = meta_map.get(prop)
            if target:
                parsed = self.parse_date_string(content)
                if target == 'published':
                    published = pick(published, parsed)
                else:
                    updated = pick(updated, parsed)
                if published and updated:
                    break

        # <time> tags
        for time_tag in soup.find_all('time'):
            datetime_attr = time_tag.get('datetime')
            parsed = self.parse_date_string(datetime_attr or time_tag.get_text(strip=True))
            if parsed:
                if not published:
                    published = parsed
                elif not updated and parsed != published:
                    updated = parsed

        return {
            'published_at': published,
            'updated_at': updated
        }

    def detect_language(
        self,
        html_content: Optional[str],
        head_headers: Optional[Dict[str, str]],
        url: Optional[str] = None,
        sitemap_entry: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """
        Prefer sitemap JSON language when available; fallback to headers/HTML lang.
        Returns an uppercased language code when found.
        """
        entry = sitemap_entry or (self._lookup_sitemap_entry(url) if url else None)
        if entry and entry.get("language"):
            return entry["language"].upper()

        if head_headers:
            content_lang = head_headers.get('content-language')
            if content_lang:
                lang_val = content_lang.split(',')[0].split(';')[0].strip().lower()
                if lang_val:
                    return lang_val.upper()

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            html_tag = soup.find('html')
            if html_tag and html_tag.get('lang'):
                lang_val = html_tag.get('lang').split('-')[0].strip().lower()
                if lang_val:
                    return lang_val.upper()

            meta_lang = soup.find('meta', attrs={'http-equiv': 'Content-Language'})
            if meta_lang and meta_lang.get('content'):
                lang_val = meta_lang.get('content').split(',')[0].split(';')[0].strip().lower()
                if lang_val:
                    return lang_val.upper()

        return None
