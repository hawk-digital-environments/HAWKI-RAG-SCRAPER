import hashlib
import re
from datetime import datetime
from typing import Any, Dict, Optional, List, TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
import html2text
from crawl4ai import AsyncWebCrawler

from src.crawler.core.service_helpers import clean_html_for_markdown, filter_markdown_lines
from src.crawler.core.service_helpers import finalize_markdown_content, normalize_whitespace
from src.crawler.core.service_utils import assess_content_quality, detect_language_confidence
from src.crawler.storage.page_output import build_page_metadata

if TYPE_CHECKING:
    from src.crawler.core.protocols import CrawlerServiceProtocol


class ServiceParseContentMixin:
    def _site_profile_extractors(self: "CrawlerServiceProtocol") -> Dict[str, List[str]]:
        profile = (getattr(self, "site_profile", {}) or {}).get("content", {})
        return {
            "selectors": profile.get("content_selectors") or [],
            "noise_phrases": profile.get("noise_phrases") or [],
            "noise_patterns": profile.get("noise_patterns") or [],
            "tag_selectors": profile.get("tag_selectors") or [],
        }

    def _extract_tags(self, soup: BeautifulSoup, selectors: Optional[List[str]] = None) -> List[str]:
        tags: List[str] = []
        default_selectors = ["meta[property='article:tag']", "meta[name='keywords']"]
        for selector in (selectors or []) + default_selectors:
            try:
                for node in soup.select(selector):
                    value = node.get("content") or node.get_text(" ", strip=True)
                    if not value:
                        continue
                    for part in re.split(r"[,;|]", value):
                        cleaned = normalize_whitespace(part)
                        if cleaned and cleaned not in tags:
                            tags.append(cleaned)
            except Exception:
                continue
        return tags

    def _fix_mojibake(self, text: str) -> str:
        """Attempt to fix UTF-8 text that was decoded as latin-1/Windows-1252."""
        if not text:
            return text
        if not re.search(r"[Ãâ�]", text):
            return text
        try:
            repaired = text.encode("latin1").decode("utf-8")
        except Exception:
            return text
        original_score = text.count("Ã") + text.count("â")
        repaired_score = repaired.count("Ã") + repaired.count("â")
        return repaired if repaired_score < original_score else text

    async def extract_page_data(
        self: "CrawlerServiceProtocol",
        url: str,
        crawler: AsyncWebCrawler,
        page_number: int,
        head_headers: Optional[Dict[str, str]] = None,
        head_status: Optional[int] = None,
        depth: int = 0,
        source_type: str = "seed",
        url_hash: Optional[str] = None,
        crawl_result: Optional[Any] = None
    ) -> Optional[Dict]:
        """Extract data from a single page"""
        try:
            if crawl_result is None:
                await self.rate_limiter.acquire()
                run_config = self.build_run_config()
                result = await crawler.arun(url=url, config=run_config)
            else:
                result = crawl_result

            if self.progress_tracker:
                await self.progress_tracker.increment_requests()

            if not result.success:
                self.job_logger.error("crawl4ai failure for %s: %s", url, result.error_message)
                if self.progress_tracker:
                    await self.progress_tracker.increment_errors()
                return None

            extractor_profile = self._site_profile_extractors()
            content_selection = clean_html_for_markdown(
                result.html,
                max_link_density=self.config.max_link_density,
                max_link_density_words=self.config.max_link_density_words,
                site_selectors=extractor_profile["selectors"],
                site_noise_phrases=extractor_profile["noise_phrases"],
                site_noise_patterns=extractor_profile["noise_patterns"],
            )
            cleaned_html = content_selection["html"]

            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            h.ignore_images = False
            markdown_content = h.handle(cleaned_html)
            fallback_used = False

            if not markdown_content or len(markdown_content.strip()) <= 1:
                fallback_used = True
                self.job_logger.warning(
                    "html2text produced empty output, using BeautifulSoup text extraction for %s",
                    url,
                )
                soup_temp = BeautifulSoup(cleaned_html, 'html.parser')
                main_content = soup_temp.find('body') or soup_temp
                text_content = main_content.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                markdown_content = '\n\n'.join(lines)

            markdown_content = self._fix_mojibake(markdown_content)
            markdown_content = filter_markdown_lines(
                markdown_content,
                site_noise_phrases=extractor_profile["noise_phrases"],
            )
            markdown_content = normalize_whitespace(markdown_content.replace("\n", "\n")).replace(" \n", "\n")
            markdown_content, markdown_cleanup_warnings = finalize_markdown_content(
                markdown_content,
                site_noise_phrases=extractor_profile["noise_phrases"],
            )
            low_quality_content = None
            soup = BeautifulSoup(result.html, 'html.parser')
            language_confidence = detect_language_confidence(lang=None, markdown=markdown_content)
            selected_details = content_selection.get("candidate_details", [{}])
            best_candidate = selected_details[0] if selected_details else {}
            quality = assess_content_quality(
                markdown_content,
                self.config.min_word_count,
                link_density=best_candidate.get("link_density", 0.0),
                heading_count=best_candidate.get("heading_count", 0),
                paragraph_count=best_candidate.get("paragraph_count", 0),
                duplicate_ratio=best_candidate.get("duplicate_ratio", 0.0),
                boilerplate_ratio=best_candidate.get("boilerplate_ratio", 0.0),
                language_confidence=language_confidence,
            )
            quality_classification = quality.get("content_classification")
            quality_word_count = int((quality.get("signals") or {}).get("word_count") or 0)
            should_demote = (
                quality_classification == "empty"
                or (quality_classification == "partial" and quality_word_count < 45)
            )
            if should_demote:
                low_quality_content = markdown_content
                markdown_content = ""

            title = None
            title_tag = soup.find('title')
            if title_tag:
                title = self._fix_mojibake(title_tag.text.strip())
            canonical_url = None
            canonical_tag = soup.find('link', rel='canonical')
            if canonical_tag and canonical_tag.get('href'):
                canonical_url = urljoin(url, canonical_tag['href'])

            final_url = getattr(result, 'final_url', None) or getattr(result, 'page_url', None)
            entry = self.first_sitemap_entry(url, final_url)

            meta_img_url = None
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                meta_img_url = urljoin(url, og_image['content'])

            lang = self.detect_language(result.html, head_headers, url=final_url or url, sitemap_entry=entry)
            quality["signals"]["language_confidence"] = detect_language_confidence(lang, low_quality_content or markdown_content)
            sitemap_date = self.get_sitemap_date(entry)
            if not sitemap_date and self.url_tracking_manager:
                url_state = await self.url_tracking_manager.get_url_state(final_url or url)
                if not url_state and final_url and final_url != url:
                    url_state = await self.url_tracking_manager.get_url_state(url)
                if url_state:
                    sitemap_date = url_state.get("sitemap_date")
            published_at = sitemap_date
            updated_at = sitemap_date or self.parse_http_date((head_headers or {}).get("last-modified"))

            tags = self._extract_tags(soup, extractor_profile["tag_selectors"])

            images = []
            images_truncated = False
            if not self.config.skip_images:
                image_exceptions = []
                if self.config.image_exceptions:
                    image_exceptions = [s.strip() for s in self.config.image_exceptions.split(',')]

                for img in (result.media or {}).get('images', []):
                    img_src = img.get('src', '')
                    if img_src:
                        should_exclude = False
                        if image_exceptions:
                            for exception in image_exceptions:
                                if soup.find(exception):
                                    matching_imgs = soup.select(f"{exception} img")
                                    for match_img in matching_imgs:
                                        if match_img.get('src') == img_src:
                                            should_exclude = True
                                            break

                        if not should_exclude:
                            absolute_img_url = urljoin(url, img_src)
                            if not urlparse(absolute_img_url).path.lower().endswith("piwik.php"):
                                images.append(absolute_img_url)

                if len(images) == 0:
                    img_tags = soup.find_all('img')
                    for img_tag in img_tags:
                        img_src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                        if img_src and img_src.startswith(('http', '/')):
                            if not img_src.startswith('data:'):
                                absolute_img_url = urljoin(url, img_src)
                                if absolute_img_url not in images:
                                    images.append(absolute_img_url)

                max_images = max(0, int(getattr(self.config, "max_images_per_page", 30)))
                if max_images and len(images) > max_images:
                    images = images[:max_images]
                    images_truncated = True

            downloaded_images = []
            if images and not self.config.skip_images:
                if url_hash and self.storage_manager:
                    self.storage_manager.create_hash_directory(url_hash, create_images_dir=True)
                    images_dir = self.storage_manager.get_hash_images_directory(url_hash)
                else:
                    page_dir = await self.create_page_directory(page_number)
                    images_dir = page_dir / "images"

                async with aiohttp.ClientSession(headers=self.headers) as session:
                    for img_url in images:
                        filename = await self.download_image(img_url, session, images_dir)
                        if filename:
                            downloaded_images.append({
                                "url": img_url,
                                "filename": filename,
                                "relative_path": f"images/{filename}",
                            })

            content_for_hash = markdown_content if markdown_content else result.html
            content_hash = hashlib.sha256(content_for_hash.encode('utf-8', errors='ignore')).hexdigest()

            fetch_time = datetime.now().isoformat()

            content_length = len((result.html or "")) if result and result.html else None
            extraction_warnings = []
            missing_fields = []
            if not title:
                missing_fields.append("title")
            if not markdown_content and low_quality_content:
                extraction_warnings.append("content_demoted_to_partial_due_to_quality")
            if not markdown_content and not low_quality_content:
                extraction_warnings.append("content_empty_after_extraction")
            if fallback_used:
                extraction_warnings.append("markdown_fallback_used")
            if images_truncated:
                extraction_warnings.append(f"images_truncated_to_{getattr(self.config, 'max_images_per_page', 30)}")
            extraction_warnings.extend(markdown_cleanup_warnings)
            dropped_sections = content_selection.get("dropped_sections", [])[:20]
            extraction_warnings.extend(dropped_sections[:10])
            raw_content_retained = bool(result.html) and (bool(low_quality_content) or not bool(markdown_content))

            if self.config.skip_images:
                image_entries = [{"url": img_url} for img_url in images]
            else:
                image_entries = downloaded_images

            page_data = build_page_metadata(
                url=final_url or url,
                source_url=url,
                url_hash=url_hash,
                canonical_url=canonical_url,
                title=title,
                lang=lang,
                fetched_at=fetch_time,
                published_at=published_at,
                updated_at=updated_at,
                tags=tags,
                images=image_entries,
                meta_image_url=meta_img_url,
                pdfs=[],
                files=[],
                http_status=head_status,
                content_length=content_length,
                content_hash=content_hash,
                quality=quality,
                markdown=markdown_content,
                low_quality_content=low_quality_content,
                source_type=source_type,
                depth=depth,
                extraction_warnings=extraction_warnings,
                missing_fields=missing_fields,
                dropped_sections=dropped_sections,
                fallback_used=fallback_used,
                raw_content_retained=raw_content_retained,
                provenance={
                    "title": "html_title" if title else "missing",
                    "canonical_url": "link_rel_canonical" if canonical_url else "url_fallback",
                    "published_at": "sitemap_or_tracking" if published_at else "missing",
                    "updated_at": "sitemap_or_last_modified" if updated_at else "missing",
                    "content": content_selection.get("selected_via", "unknown"),
                    "tags": "meta_tags" if tags else "missing",
                },
            )

            return {
                'data': page_data,
                'markdown': markdown_content,
                'low_quality_content': low_quality_content,
                'html_content': result.html
            }

        except Exception as e:
            error_text = str(e)
            if "Browser.new_context" in error_text and "Target page, context or browser has been closed" in error_text:
                raise RuntimeError(f"browser_closed:{url}") from e
            self.job_logger.error("Error extracting data from %s: %s", url, e)
            return None
