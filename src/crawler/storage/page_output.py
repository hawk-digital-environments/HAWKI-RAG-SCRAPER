from __future__ import annotations

import json
import math
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "1.0"
PAGE_ROOT_DIRNAME = "pages"
CONTENT_FILENAME = "content.md"
METADATA_FILENAME = "data.json"
DIAGNOSTICS_DIRNAME = "diagnostics"
ALLOWED_PAGE_ENTRIES = {
    CONTENT_FILENAME,
    METADATA_FILENAME,
    "images",
    "files",
    DIAGNOSTICS_DIRNAME,
}


def _first_string(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _first_string(item)
            if text:
                return text
        return ""
    if value is None:
        return ""
    return normalize_scalar(value) or ""


def _optional_string(value: Any) -> Optional[str]:
    text = normalize_scalar(value)
    return text or None


def normalize_scalar(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if text.lower() in {"none", "null", "n/a", "undefined", "nan"}:
        return None
    return text


def canonicalize_url(value: Any) -> Optional[str]:
    text = normalize_scalar(value)
    if not text:
        return None
    try:
        parts = urlsplit(text)
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        path = parts.path or "/"
        if path != "/":
            path = path.rstrip("/") or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    except Exception:
        return text


def _normalize_tags(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [normalize_scalar(item) for item in value if normalize_scalar(item)]
    normalized = normalize_scalar(value)
    return [normalized] if normalized else []


def _word_count(text: str) -> int:
    return len([token for token in (text or "").split() if token.strip()])


def _normalize_asset_entries(
    entries: Optional[List[Dict[str, Any]]],
    asset_dir: str,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_urls = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        asset_url = canonicalize_url(entry.get("url"))
        if asset_url and asset_url in seen_urls:
            continue
        if asset_url:
            seen_urls.add(asset_url)
        filename = _optional_string(entry.get("filename"))
        relative_path = _optional_string(entry.get("relative_path"))
        if not relative_path and filename:
            relative_path = f"{asset_dir}/{filename}"
        normalized.append(
            {
                "url": asset_url,
                "filename": filename,
                "relative_path": relative_path,
                "content_type": _optional_string(entry.get("content_type")),
                "incomplete": bool(entry.get("incomplete", False)),
                "error": _optional_string(entry.get("error")),
            }
        )
    return normalized


def determine_content_status(
    markdown: str,
    low_quality_content: Optional[str] = None,
    has_binary_assets: bool = False,
    quality_classification: Optional[str] = None,
) -> str:
    if markdown and markdown.strip():
        if quality_classification == "noisy":
            return "noisy"
        return "success"
    if low_quality_content and low_quality_content.strip():
        return "partial"
    if has_binary_assets:
        return "binary"
    return "empty"


def build_page_metadata(
    *,
    url: str,
    url_hash: Optional[str],
    source_url: Optional[str] = None,
    canonical_url: Optional[str] = None,
    title: Any = None,
    lang: Optional[str] = None,
    fetched_at: Optional[str] = None,
    published_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    tags: Any = None,
    images: Optional[List[Dict[str, Any]]] = None,
    meta_image_url: Optional[str] = None,
    pdfs: Optional[List[Dict[str, Any]]] = None,
    files: Optional[List[Dict[str, Any]]] = None,
    http_status: Optional[int] = None,
    content_length: Optional[int] = None,
    content_hash: Optional[str] = None,
    quality: Optional[Dict[str, Any]] = None,
    markdown: str = "",
    low_quality_content: Optional[str] = None,
    source_type: str = "seed",
    depth: int = 0,
    extraction_warnings: Optional[List[str]] = None,
    missing_fields: Optional[List[str]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    dropped_sections: Optional[List[str]] = None,
    fallback_used: bool = False,
    raw_content_retained: bool = False,
) -> Dict[str, Any]:
    image_entries = _normalize_asset_entries(images, "images")
    pdf_entries = _normalize_asset_entries(pdfs, "files")
    file_entries = _normalize_asset_entries(files, "files")
    has_binary_assets = bool(pdf_entries or file_entries)
    content_status = determine_content_status(
        markdown=markdown,
        low_quality_content=low_quality_content,
        has_binary_assets=has_binary_assets,
        quality_classification=(quality or {}).get("content_classification"),
    )
    effective_text = markdown if markdown and markdown.strip() else (low_quality_content or "")
    primary_image = _optional_string(meta_image_url)
    if not primary_image:
        for image in image_entries:
            if image.get("url"):
                primary_image = image["url"]
                break

    extraction_warnings = [warning for warning in (extraction_warnings or []) if normalize_scalar(warning)]
    missing_fields = [field for field in (missing_fields or []) if normalize_scalar(field)]
    dropped_sections = [section for section in (dropped_sections or []) if normalize_scalar(section)]

    return {
        "schema_version": SCHEMA_VERSION,
        "page_id": url_hash or _optional_string(url),
        "url": canonicalize_url(url),
        "source_url": canonicalize_url(source_url) or canonicalize_url(url),
        "canonical_url": canonicalize_url(canonical_url) or canonicalize_url(url),
        "title": _optional_string(title),
        "tags": _normalize_tags(tags),
        "lang": _optional_string(lang),
        "timestamps": {
            "fetched_at": _optional_string(fetched_at),
            "published_at": _optional_string(published_at),
            "updated_at": _optional_string(updated_at),
        },
        "status": {
            "http_status": http_status,
            "content_status": content_status,
            "is_empty": content_status in {"empty", "binary"},
            "is_partial": content_status == "partial",
            "word_count": _word_count(effective_text),
        },
        "files": {
            "content_markdown": CONTENT_FILENAME,
            "metadata_json": METADATA_FILENAME,
        },
        "images": image_entries,
        "primary_image": primary_image,
        "documents": {
            "pdfs": pdf_entries,
            "files": file_entries,
        },
        "hashes": {
            "url_sha256": _optional_string(url_hash),
            "content_sha256": _optional_string(content_hash),
        },
        "source": {
            "type": _optional_string(source_type) or "seed",
            "depth": max(int(depth or 0), 0),
        },
        "content_length": content_length,
        "quality": quality or {},
        "extraction_warnings": extraction_warnings,
        "missing_fields": missing_fields,
        "dropped_sections": dropped_sections,
        "fallback_used": bool(fallback_used),
        "raw_content_retained": bool(raw_content_retained),
        "provenance": provenance or {},
    }


def _collect_page_directories(job_dir: Path) -> List[Path]:
    pages_root = job_dir / PAGE_ROOT_DIRNAME
    if not pages_root.exists():
        return []
    return sorted(
        path.parent
        for path in pages_root.rglob(METADATA_FILENAME)
        if path.is_file()
    )


def validate_page_directory(page_dir: Path) -> List[str]:
    errors: List[str] = []
    content_file = page_dir / CONTENT_FILENAME
    metadata_file = page_dir / METADATA_FILENAME

    if not metadata_file.exists():
        errors.append(f"{page_dir}: missing {METADATA_FILENAME}")
        return errors
    if not content_file.exists():
        errors.append(f"{page_dir}: missing {CONTENT_FILENAME}")

    for entry in page_dir.iterdir():
        if entry.name not in ALLOWED_PAGE_ENTRIES:
            errors.append(f"{page_dir}: unexpected entry {entry.name}")

    raw_metadata_text = metadata_file.read_text(encoding="utf-8")
    try:
        metadata = json.loads(raw_metadata_text)
    except Exception as exc:
        errors.append(f"{metadata_file}: invalid JSON ({exc})")
        return errors

    required_fields = [
        "schema_version",
        "page_id",
        "url",
        "title",
        "timestamps",
        "status",
        "files",
        "images",
        "documents",
        "hashes",
        "source",
        "extraction_warnings",
        "missing_fields",
        "dropped_sections",
        "fallback_used",
        "raw_content_retained",
        "provenance",
    ]
    for field in required_fields:
        if field not in metadata:
            errors.append(f"{metadata_file}: missing field {field}")

    files_info = metadata.get("files", {})
    if files_info.get("content_markdown") != CONTENT_FILENAME:
        errors.append(f"{metadata_file}: files.content_markdown must be {CONTENT_FILENAME}")
    if files_info.get("metadata_json") != METADATA_FILENAME:
        errors.append(f"{metadata_file}: files.metadata_json must be {METADATA_FILENAME}")

    timestamps = metadata.get("timestamps", {})
    if "fetched_at" not in timestamps:
        errors.append(f"{metadata_file}: timestamps.fetched_at is required")
    for key in ("fetched_at", "published_at", "updated_at"):
        value = timestamps.get(key)
        if value:
            try:
                datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except Exception:
                errors.append(f"{metadata_file}: timestamps.{key} is not valid ISO-8601")

    for bad_string in ('"NaN"', '"N/A"', '"undefined"', '"null"', '"None"'):
        if bad_string in raw_metadata_text:
            errors.append(f"{metadata_file}: contains disallowed string literal {bad_string}")

    status = metadata.get("status", {})
    markdown_text = content_file.read_text(encoding="utf-8")
    if status.get("content_status") == "success" and not markdown_text.strip():
        errors.append(f"{page_dir}: success page must have non-empty content.md")
    if status.get("content_status") in {"partial", "noisy"} and metadata.get("quality", {}).get("score", 100) > 80:
        errors.append(f"{metadata_file}: content_status disagrees with quality.score")

    page_url = metadata.get("url")
    canonical_url = metadata.get("canonical_url")
    if not page_url or "://" not in str(page_url):
        errors.append(f"{metadata_file}: url is missing or malformed")
    if canonical_url and "://" not in str(canonical_url):
        errors.append(f"{metadata_file}: canonical_url is malformed")
    hashes = metadata.get("hashes", {})
    for hash_key in ("url_sha256", "content_sha256"):
        hash_value = hashes.get(hash_key)
        if hash_value and not re.fullmatch(r"[a-fA-F0-9]{8,64}", str(hash_value)):
            errors.append(f"{metadata_file}: {hash_key} is malformed")

    word_count = metadata.get("status", {}).get("word_count", 0)
    if word_count >= 80 and not metadata.get("title"):
        errors.append(f"{metadata_file}: long-form page is missing title")
    if metadata.get("quality", {}).get("signals", {}).get("boilerplate_ratio", 0) > 0.5:
        errors.append(f"{metadata_file}: excessive boilerplate_ratio")

    for asset_group in (metadata.get("images", []), metadata.get("documents", {}).get("pdfs", []), metadata.get("documents", {}).get("files", [])):
        for asset in asset_group:
            relative_path = asset.get("relative_path")
            if relative_path and not (page_dir / relative_path).exists():
                errors.append(f"{metadata_file}: referenced asset missing at {relative_path}")

    return errors


def validate_job_directory(job_dir: Path) -> List[str]:
    errors: List[str] = []
    page_directories = _collect_page_directories(job_dir)
    if not page_directories:
        return [f"{job_dir}: no page metadata found under {PAGE_ROOT_DIRNAME}/"]
    seen_hashes: Dict[str, Path] = {}
    for page_dir in page_directories:
        errors.extend(validate_page_directory(page_dir))
        metadata_file = page_dir / METADATA_FILENAME
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        content_hash = ((metadata.get("hashes") or {}).get("content_sha256"))
        if content_hash:
            if content_hash in seen_hashes:
                errors.append(
                    f"{job_dir}: duplicate content_sha256 {content_hash} in {seen_hashes[content_hash]} and {page_dir}"
                )
            else:
                seen_hashes[content_hash] = page_dir
    return errors
