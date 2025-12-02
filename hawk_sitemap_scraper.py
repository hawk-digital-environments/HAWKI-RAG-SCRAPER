"""
HAWK sitemap extraction utility using crawl4ai.
"""
import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
import unicodedata
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig


LOGGER = logging.getLogger(__name__)
DEFAULT_SITEMAP_BASE = "https://www.hawk.de/sitemaps/main/sitemap.xml"
DEFAULT_TIMEOUT_MS = 150000
DEFAULT_WAIT_UNTIL = "domcontentloaded"
DEFAULT_MAX_RETRIES = 2


def _clean_text(text: str) -> str:
    return (text or "").replace("\xa0", " ").strip()


class HawkSitemapScraper:
    """Scrape the  HAWK sitemap table and build a JSON index."""

    def __init__(
        self,
        base_url: str = DEFAULT_SITEMAP_BASE,
        start_page: int = 1,
        max_pages: int = 6,
        output_path: Union[Path, str] = Path("data/hawk_sitemap.json"),
        page_timeout: int = DEFAULT_TIMEOUT_MS,
        wait_until: str = DEFAULT_WAIT_UNTIL,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.base_url = base_url.rstrip("/")
        self.start_page = start_page
        self.max_pages = max_pages
        self.output_path = Path(output_path)
        self.page_timeout = page_timeout
        self.wait_until = wait_until
        self.max_retries = max_retries
        self.run_config = CrawlerRunConfig(
            word_count_threshold=0,
            exclude_external_links=True,
            process_iframes=False,
            remove_overlay_elements=False,
            cache_mode=CacheMode.BYPASS,
            wait_until=self.wait_until,
            page_timeout=self.page_timeout,
            delay_before_return_html=3.5,
        )

    def _build_page_url(self, page_number: int) -> str:
        return f"{self.base_url}?page={page_number}"

    async def _fetch_page_html(self, crawler: AsyncWebCrawler, url: str) -> Optional[str]:
        """Render a sitemap page and return HTML."""
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                result = await crawler.arun(url=url, config=self.run_config)
            except Exception as exc:
                LOGGER.warning("Failed to render %s (attempt %s/%s): %s", url, attempt, attempts, exc)
                result = None

            if result and result.success and result.html and result.html.strip():
                return result.html

            reason = result.error_message if result else "no result"
            LOGGER.warning(
                "crawl4ai reported failure for %s (attempt %s/%s): %s",
                url,
                attempt,
                attempts,
                reason,
            )

            if attempt < attempts:
                backoff = min(10, 2 ** (attempt - 1))
                LOGGER.info("Retrying %s in %ss", url, backoff)
                await asyncio.sleep(backoff)

        return None

    @staticmethod
    def _resolve_column_indexes(headers: List[str]) -> Dict[str, int]:
        normalized = [
            unicodedata.normalize("NFKD", h).encode("ascii", "ignore").decode().lower() for h in headers
        ] or [""]
        find = lambda keys, default: next(
            (i for i, h in enumerate(normalized) if any(k in h for k in keys)), default
        )
        return {
            "url": find(["url"], 0),
            "last_modified": find(["letztes", "lastmod", "geandert", "modified"], 1),
            "language": find(["uebersetzungsgruppe", "ubersetzungsgruppe", "translation", "sprache"], 4),
        }

    @staticmethod
    def _extract_url(cell) -> Optional[str]:
        if not cell:
            return None
        link = cell.find("a")
        if link and link.get("href"):
            return _clean_text(link.get("href"))
        return _clean_text(cell.get_text(" ", strip=True))

    @staticmethod
    def _extract_last_modified(cell) -> Optional[str]:
        if not cell:
            return None
        time_tag = cell.find("time")
        if time_tag:
            for attr in ("datetime", "content"):
                if time_tag.get(attr):
                    return _clean_text(time_tag[attr])
        return _clean_text(cell.get_text(" ", strip=True))

    @staticmethod
    def _language_from_url(url: str) -> Optional[str]:
        """
        Infer language from URL by looking at the first path segment (between the 3rd and 4th slash).
        Example: https://www.hawk.de/en/... -> EN, https://www.hawk.de/de/... -> DE
        """
        if not url:
            return None
        try:
            cleaned = _clean_text(url)
            parsed = urlparse(cleaned)
        except Exception:
            return None

        # Regex-based extraction between the 3rd and 4th slash
        match = re.search(r"^https?://[^/]+/([^/]+)/", cleaned, re.IGNORECASE)
        if not match and cleaned.startswith("/"):
            match = re.search(r"^/([^/]+)/", cleaned, re.IGNORECASE)
        if match:
            candidate = match.group(1).lower()
            if candidate.startswith("en"):
                return "EN"
            if candidate.startswith("de"):
                return "DE"

        # Fallback to path splitting
        path = parsed.path or ""
        parts = [p for p in path.split("/") if p]
        if parts:
            candidate = parts[0].lower()
            if candidate.startswith("en"):
                return "EN"
            if candidate.startswith("de"):
                return "DE"

        # As a fallback, check if the path contains /en/ or /de/
        lowered_path = path.lower()
        if "/en/" in lowered_path or lowered_path.startswith("/en"):
            return "EN"
        if "/de/" in lowered_path or lowered_path.startswith("/de"):
            return "DE"

        return None

    def _parse_table(self, html: str, page_number: int) -> Dict[str, Dict[str, Optional[str]]]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return {}

        headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        indexes = self._resolve_column_indexes(headers)
        url_idx, lastmod_idx = indexes["url"], indexes["last_modified"]

        tbody = table.find("tbody") or table
        data: Dict[str, Dict[str, Optional[str]]] = {}

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            url_cell = cells[url_idx] if url_idx is not None and url_idx < len(cells) else None
            lastmod_cell = cells[lastmod_idx] if lastmod_idx is not None and lastmod_idx < len(cells) else None
            url_value = self._extract_url(url_cell)
            if not url_value:
                continue

            last_modified = self._extract_last_modified(lastmod_cell)
            language = self._language_from_url(url_value)

            data[url_value] = {
                "language": language or "unknown",
                "last_modified": last_modified,
                "source_page": page_number,
            }

        # Log a single sample row for debugging language parsing
        if data:
            sample_url = next(iter(data.keys()))
            sample_lang = data[sample_url]["language"]
            sample_path = urlparse(sample_url).path if sample_url else ""
            LOGGER.info(
                "Sample row from page %s -> url: %s | language: %s | path: %s | last_modified: %s",
                page_number,
                sample_url,
                sample_lang,
                sample_path,
                data[sample_url]["last_modified"],
            )

        return data

    async def scrape(self) -> Dict[str, Dict[str, Optional[str]]]:
        output: Dict[str, Dict[str, Optional[str]]] = {}
        total_parsed = 0

        browser_config = BrowserConfig(headless=True, verbose=False)
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for page in range(self.start_page, self.start_page + self.max_pages):
                page_url = self._build_page_url(page)
                html = await self._fetch_page_html(crawler, page_url)
                if not html:
                    LOGGER.info("No HTML for page %s, continuing to next page.", page)
                    continue

                page_data = self._parse_table(html, page)
                if not page_data:
                    LOGGER.info("No rows parsed from %s, continuing.", page_url)
                    continue

                total_parsed += len(page_data)
                output.update(page_data)
                LOGGER.info(
                    "Parsed %s entries from page %s (running total before dedup: %s)",
                    len(page_data),
                    page,
                    total_parsed,
                )

        LOGGER.info(
            "Finished pagination. Parsed rows (pre-dedup): %s, unique URLs saved: %s",
            total_parsed,
            len(output),
        )
        self._write_output(output)
        return output

    def _write_output(self, data: Dict[str, Dict[str, Optional[str]]]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        LOGGER.info("Saved %s records to %s", len(data), self.output_path)


async def _run_hawk_sitemap(args) -> None:
    scraper = HawkSitemapScraper(
        base_url=args.base_url,
        start_page=args.start_page,
        max_pages=args.pages,
        output_path=args.output,
        page_timeout=args.timeout_ms,
        wait_until=args.wait_until,
        max_retries=args.retries,
    )
    await scraper.scrape()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HAWK sitemap scraper")
    parser.add_argument(
        "--hawk-sitemap",
        action="store_true",
        help="Render the HAWK sitemap pages and write a JSON map of URL -> metadata.",
    )
    parser.add_argument("--base-url", default=DEFAULT_SITEMAP_BASE, help="Base sitemap URL (without page param).")
    parser.add_argument("--start-page", type=int, default=1, help="First sitemap page to request.")
    parser.add_argument(
        "--pages",
        type=int,
        default=6,
        help="Maximum number of paginated sitemap pages to attempt before stopping.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="Page timeout in milliseconds for each sitemap page render.",
    )
    parser.add_argument(
        "--wait-until",
        type=str,
        default=DEFAULT_WAIT_UNTIL,
        choices=["domcontentloaded", "networkidle", "load"],
        help="Playwright waitUntil condition before extracting HTML.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Number of retry attempts per page before skipping.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/hawk_sitemap.json",
        help="Where to store the generated JSON map.",
    )
    return parser


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.hawk_sitemap:
        parser.print_help()
        return

    asyncio.run(_run_hawk_sitemap(args))


if __name__ == "__main__":
    main()
