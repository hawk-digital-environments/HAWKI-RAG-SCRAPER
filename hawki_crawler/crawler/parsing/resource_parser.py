import mimetypes
import os
import re
from typing import Callable, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hawki_crawler.crawler.policies.resource_policy import ResourcePolicy


class ResourceParser:
    """Extract resource links and derive safe filenames from responses."""

    def __init__(self, resource_policy: ResourcePolicy) -> None:
        self.resource_policy = resource_policy

    def extract_pdf_links(self, html_content: str, base_url: str) -> List[str]:
        return self._extract_links(
            html_content,
            base_url,
            is_resource_url=self.resource_policy.is_pdf_url,
        )

    def extract_file_links(self, html_content: str, base_url: str) -> List[str]:
        return self._extract_links(
            html_content,
            base_url,
            is_resource_url=self.resource_policy.is_file_url,
        )

    @staticmethod
    def _extract_links(
        html_content: str,
        base_url: str,
        *,
        is_resource_url: Callable[[str], bool],
    ) -> List[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        links = []
        for anchor in soup.find_all("a"):
            href = anchor.get("href")
            if not href:
                continue
            absolute_url = urljoin(base_url, href)
            if is_resource_url(absolute_url):
                links.append(absolute_url)
        return links

    @staticmethod
    def filename_from_content_disposition(header_value: str) -> Optional[str]:
        if not header_value:
            return None
        match = re.search(
            r"filename\*?=(?:UTF-8''|\")?([^\";]+)",
            header_value,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def pdf_filename_from_url(url: str) -> str:
        filename = os.path.basename(urlparse(url).path)
        if not filename or not filename.lower().endswith(".pdf"):
            filename = f"file_{abs(hash(url))}.pdf"
        return ResourceParser.sanitize_filename(filename, pattern=r"[^\w\-_\.]")

    @staticmethod
    def file_filename_from_response(
        url: str,
        content_type: str,
        content_disposition: str,
    ) -> str:
        filename = ResourceParser.filename_from_content_disposition(content_disposition)
        if not filename:
            filename = os.path.basename(urlparse(url).path)
        if not filename:
            extension = mimetypes.guess_extension(content_type or "") or ".bin"
            filename = f"file_{abs(hash(url))}{extension}"
        return ResourceParser.sanitize_filename(filename, pattern=r"[^A-Za-z0-9._-]")

    @staticmethod
    def sanitize_filename(filename: str, *, pattern: str) -> str:
        umlaut_map = str.maketrans(
            {
                "ä": "ae",
                "ö": "oe",
                "ü": "ue",
                "Ä": "Ae",
                "Ö": "Oe",
                "Ü": "Ue",
                "ß": "ss",
            }
        )
        return re.sub(pattern, "_", filename.translate(umlaut_map))
