import mimetypes
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


FILE_EXTENSIONS = (
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
    ".odp", ".rtf", ".txt", ".csv", ".zip", ".rar", ".7z",
)
DISALLOWED_FILE_EXTENSIONS = (".exe",)


class AssetPolicy:
    """Pure asset classification and filename rules used by crawler downloads."""

    def extract_pdf_links(self, html_content: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        pdf_links = []
        for a in soup.find_all("a"):
            href = a.get("href")
            if not href:
                continue
            absolute_url = urljoin(base_url, href)
            if self.is_pdf_url(absolute_url):
                pdf_links.append(absolute_url)
        return pdf_links

    def extract_file_links(self, html_content: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html_content, "html.parser")
        file_links = []
        for a in soup.find_all("a"):
            href = a.get("href")
            if not href:
                continue
            absolute_url = urljoin(base_url, href)
            if self.is_file_url(absolute_url):
                file_links.append(absolute_url)
        return file_links

    def is_pdf_url(self, url: str) -> bool:
        return url.lower().split("?")[0].endswith(".pdf")

    def is_file_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(DISALLOWED_FILE_EXTENSIONS):
            return False
        if path.endswith(".pdf"):
            return False
        return path.endswith(FILE_EXTENSIONS)

    def looks_like_file_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(DISALLOWED_FILE_EXTENSIONS):
            return True
        if path.endswith(".pdf"):
            return True
        if path.endswith(FILE_EXTENSIONS):
            return True
        if "/media/" in path and not path.endswith(".pdf"):
            return True
        return False

    def is_pdf_resource(self, url: str, headers: Optional[Dict[str, str]] = None) -> bool:
        if self.is_pdf_url(url):
            return True
        content_type = (headers or {}).get("content-type", "")
        return "pdf" in content_type.lower()

    def is_file_resource(self, url: str, headers: Optional[Dict[str, str]] = None) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith(DISALLOWED_FILE_EXTENSIONS):
            return False
        if "/media/" in path and not path.endswith(".pdf"):
            return True
        if path.endswith(FILE_EXTENSIONS):
            return True
        if headers is None:
            return False

        content_type = headers.get("content-type", "").lower()
        if not content_type:
            return False
        if content_type == "application/x-msdownload":
            return False
        if "text/html" in content_type:
            return False
        if content_type.startswith("image/"):
            return False
        if content_type in ("text/css", "text/javascript", "application/javascript"):
            return False
        if "application/" in content_type or "octet-stream" in content_type:
            return True

        content_disposition = headers.get("content-disposition", "").lower()
        return "attachment" in content_disposition

    def should_skip_file_download(
        self,
        url: str,
        filename: Optional[str],
        content_type: str,
    ) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(".exe"):
            return True
        if filename and filename.lower().endswith(".exe"):
            return True
        if content_type == "application/x-msdownload":
            return True
        if not filename:
            return True
        if Path(filename).suffix == "":
            return True
        return False

    def filename_from_content_disposition(self, header_value: str) -> Optional[str]:
        if not header_value:
            return None
        match = re.search(r"filename\\*?=(?:UTF-8''|\\\")?([^\\\";]+)", header_value, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def pdf_filename_from_url(self, url: str) -> str:
        filename = os.path.basename(urlparse(url).path)
        if not filename or not filename.lower().endswith(".pdf"):
            filename = f"file_{abs(hash(url))}.pdf"
        return self.sanitize_filename(filename, pattern=r"[^\w\-_\.]")

    def file_filename_from_response(
        self,
        url: str,
        content_type: str,
        content_disposition: str,
    ) -> str:
        filename = self.filename_from_content_disposition(content_disposition)
        if not filename:
            filename = os.path.basename(urlparse(url).path)
        if not filename:
            ext = mimetypes.guess_extension(content_type or "")
            ext = ext or ".bin"
            filename = f"file_{abs(hash(url))}{ext}"
        return self.sanitize_filename(filename, pattern=r"[^A-Za-z0-9._-]")

    def sanitize_filename(self, filename: str, *, pattern: str) -> str:
        umlaut_map = str.maketrans({
            "ä": "ae", "ö": "oe", "ü": "ue",
            "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
            "ß": "ss",
        })
        filename = filename.translate(umlaut_map)
        return re.sub(pattern, "_", filename)
