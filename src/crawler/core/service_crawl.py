import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Optional, List
from urllib.parse import urlparse

import aiofiles
import aiohttp
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig

from src.crawler.communication.interface import Stage
from src.crawler.storage.url_tracking_manager import generate_url_hash
from src.crawler.storage.summary_manager import SummaryManager


class ServiceCrawlMixin:
    async def _trigger_safe_stop(self, reason: str) -> None:
        async with self.abort_lock:
            if self.abort_crawl:
                return
            self.abort_crawl = True
            self.abort_reason = reason
            self.to_visit.clear()

    async def _request_browser_restart(self, url: str) -> None:
        async with self.restart_lock:
            if url not in self.restart_urls:
                self.restart_urls.append(url)
            self.restart_crawler = True

    async def _update_total_urls(self, new_total: int) -> None:
        if new_total <= 0:
            return
        if self.job_state:
            snapshot = await self.job_state.get_snapshot()
            if new_total > snapshot.total_urls:
                await self.job_state.set_total_urls(new_total)
        if self.progress_tracker:
            progress = await self.progress_tracker.get_progress()
            if new_total > progress["total_urls"]:
                await self.progress_tracker.set_total_urls(new_total)

    async def save_page_data(self, page_data: Dict, page_number: int, url_hash: Optional[str] = None):
        """Save page data to JSON and markdown files in hash-based directory"""
        low_quality_content = page_data.get('low_quality_content')
        if self.storage_manager and url_hash:
            self.storage_manager.create_hash_directory(url_hash, create_images_dir=not self.config.skip_images)
            await self.storage_manager.save_hash_json(url_hash, page_data['data'])
            await self.storage_manager.save_hash_content(url_hash, page_data['markdown'] if page_data['markdown'] else "")
            if low_quality_content:
                low_q_file = self.storage_manager.get_hash_directory(url_hash) / "low_q.txt"
                async with aiofiles.open(low_q_file, 'w', encoding='utf-8') as f:
                    await f.write(low_quality_content)
        elif self.storage_manager:
            page_dir = await self.create_page_directory(page_number)
            await self.storage_manager.save_page_json(page_number, page_data['data'])
            await self.storage_manager.save_page_content(page_number, page_data['markdown'] if page_data['markdown'] else "")
            if low_quality_content:
                low_q_file = page_dir / "low_q.txt"
                async with aiofiles.open(low_q_file, 'w', encoding='utf-8') as f:
                    await f.write(low_quality_content)
        else:
            page_dir = await self.create_page_directory(page_number)
            json_filename = page_dir / f"data_{page_number:05d}.json"
            async with aiofiles.open(json_filename, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(page_data['data'], indent=2, ensure_ascii=False))

            md_filename = page_dir / f"content_{page_number:05d}.md"
            async with aiofiles.open(md_filename, 'w', encoding='utf-8') as f:
                await f.write(page_data['markdown'] if page_data['markdown'] else "")
            if low_quality_content:
                low_q_file = page_dir / "low_q.txt"
                async with aiofiles.open(low_q_file, 'w', encoding='utf-8') as f:
                    await f.write(low_quality_content)

    async def crawl_page(self, url: str, crawler: AsyncWebCrawler):
        """Crawl a single page"""
        async with self.semaphore:
            if self.abort_crawl:
                return

            was_failed = False
            if self.url_tracking_manager:
                prior_state = await self.url_tracking_manager.get_url_state(url)
                was_failed = (prior_state or {}).get("status") == "failed"

            parsed_url = urlparse(url)
            if parsed_url.scheme not in ("http", "https"):
                print(f"Skipping non-HTTP URL: {url}")
                async with self.counter_lock:
                    if url in self.visited_urls:
                        return
                    self.visited_urls.add(url)
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_completed(url, None)
                if self.progress_tracker:
                    if was_failed:
                        await self.progress_tracker.decrement_failed()
                    await self.progress_tracker.increment_completed()
                    await self._send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if was_failed:
                        await self.job_state.decrement_failed()
                    await self.job_state.increment_completed()
                return

            # Check if URL already visited or max pages reached
            async with self.counter_lock:
                if url in self.visited_urls or (
                    self.config.max_pages > 0
                    and self.page_counter >= self.config.max_pages
                    and not self.allow_over_max_pages
                ):
                    return

                self.visited_urls.add(url)
                self.page_counter += 1
                current_page_number = self.page_counter

            # Generate URL hash for storage
            url_hash = generate_url_hash(url)

            # Display progress
            total_pages = self.config.max_pages if self.config.max_pages > 0 else "unlimited"
            if self.config.max_pages > 0:
                print(f"Crawling [{current_page_number}/{self.config.max_pages}]: {url}")
            else:
                print(f"Crawling [{current_page_number}/unlimited]: {url}")

            # Update tracking systems
            if self.url_tracking_manager:
                await self.url_tracking_manager.set_processing(url, current_page_number)
            if self.progress_tracker:
                await self.progress_tracker.set_current_url(url)
            if self.job_state:
                await self.job_state.set_current_url(url)

            if self._is_video_url(url):
                print(f"Skipping video URL: {url}")
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_completed(url, None)
                if self.progress_tracker:
                    if was_failed:
                        await self.progress_tracker.decrement_failed()
                    await self.progress_tracker.increment_completed()
                    await self._send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if was_failed:
                        await self.job_state.decrement_failed()
                    await self.job_state.increment_completed()
                return

            head_status, head_headers = await self.fetch_head(url)
            url_host = urlparse(url).hostname
            if self.crawl_host and (
                url_host == self.crawl_host or url_host.endswith(f".{self.crawl_host}")
            ):
                if head_status is not None and head_status >= 500:
                    async with self.consecutive_5xx_lock:
                        self.consecutive_5xx += 1
                        consecutive_5xx = self.consecutive_5xx
                else:
                    async with self.consecutive_5xx_lock:
                        self.consecutive_5xx = 0
                        consecutive_5xx = 0
            else:
                consecutive_5xx = 0

            if consecutive_5xx >= 3:
                error_msg = (
                    f"Aborting crawl: received {consecutive_5xx} consecutive HTTP 5xx responses "
                    f"(last was {head_status})"
                )
                await self._trigger_safe_stop(error_msg)
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_failed(url, error_msg)
                if self.progress_tracker:
                    if not was_failed:
                        await self.progress_tracker.increment_failed()
                    await self.progress_tracker.increment_errors()
                    await self._send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if not was_failed:
                        await self.job_state.increment_failed()
                async with self.counter_lock:
                    self.page_counter -= 1
                return

            # Handle direct file URLs
            page_data = None
            if await self.is_pdf_resource(url, head_status, head_headers):
                pdf_entry = await self.fetch_and_save_pdf(url, current_page_number, url_hash=url_hash)
                if pdf_entry:
                    pdf_lang = self.detect_language(None, head_headers, url=url)
                    sitemap_entry = self._lookup_sitemap_entry(url) or {}
                    updated_at = sitemap_entry.get("last_modified")
                    if not updated_at:
                        updated_at = datetime.now().isoformat()
                    page_data = {
                        'data': {
                            'title': [],
                            'page_url': [url],
                            'url_hash': url_hash,
                            'meta_img_url': [],
                            'images': [],
                            'lang': pdf_lang,
                            'updated_at': updated_at,
                            'source_type': self.url_source.get(url, 'seed'),
                            'pdfs': [pdf_entry],
                            'files': []
                        },
                        'markdown': '',
                        'html_content': ''
                    }
            elif await self.is_file_resource(url, head_status, head_headers):
                file_entry = await self.fetch_and_save_file(url, current_page_number, url_hash=url_hash)
                if file_entry:
                    file_lang = self.detect_language(None, head_headers, url=url)
                    sitemap_entry = self._lookup_sitemap_entry(url) or {}
                    updated_at = sitemap_entry.get("last_modified")
                    if not updated_at:
                        updated_at = datetime.now().isoformat()
                    page_data = {
                        'data': {
                            'title': [],
                            'page_url': [url],
                            'url_hash': url_hash,
                            'meta_img_url': [],
                            'images': [],
                            'lang': file_lang,
                            'updated_at': updated_at,
                            'source_type': self.url_source.get(url, 'seed'),
                            'pdfs': [],
                            'files': [file_entry]
                        },
                        'markdown': '',
                        'html_content': ''
                    }
            else:
                try:
                    page_data = await self.extract_page_data(
                        url,
                        crawler,
                        current_page_number,
                        head_headers=head_headers,
                        head_status=head_status,
                        depth=self.url_depth.get(url, 0),
                        source_type=self.url_source.get(url, 'seed'),
                        url_hash=url_hash
                    )
                except RuntimeError as exc:
                    if str(exc).startswith("browser_closed:"):
                        print(f"Browser context closed; requesting restart and retry for {url}")
                        await self._request_browser_restart(url)
                        async with self.counter_lock:
                            self.page_counter -= 1
                            self.visited_urls.discard(url)
                        if self.url_tracking_manager:
                            await self.url_tracking_manager.set_pending(url)
                        return
                    raise

            if page_data:
                pdf_entries = page_data['data'].get('pdfs', [])
                file_entries = page_data['data'].get('files', [])

                if page_data.get('html_content'):
                    pdf_links = self.extract_pdf_links(page_data['html_content'], url)
                    if pdf_links:
                        async with aiohttp.ClientSession(headers=self.headers) as pdf_session:
                            for pdf_url in pdf_links:
                                pdf_entry = await self.fetch_and_save_pdf(
                                    pdf_url,
                                    current_page_number,
                                    session=pdf_session,
                                    url_hash=url_hash
                                )
                                if pdf_entry:
                                    pdf_entries.append(pdf_entry)

                    file_links = self.extract_file_links(page_data['html_content'], url)
                    if file_links:
                        async with aiohttp.ClientSession(headers=self.headers) as file_session:
                            for file_url in file_links:
                                file_entry = await self.fetch_and_save_file(
                                    file_url,
                                    current_page_number,
                                    session=file_session,
                                    url_hash=url_hash
                                )
                                if file_entry:
                                    file_entries.append(file_entry)

                page_data['data']['pdfs'] = pdf_entries
                page_data['data']['files'] = file_entries

                await self.save_page_data(page_data, current_page_number, url_hash)

                # Extract header dates for URLTrackingManager
                header_dates = None
                if head_headers:
                    header_dates = {
                        "last_modified": head_headers.get('last-modified'),
                        "date": head_headers.get('date')
                    }

                # Update tracking systems with completion
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_completed(url, header_dates)
                if self.progress_tracker:
                    if was_failed:
                        await self.progress_tracker.decrement_failed()
                    await self.progress_tracker.increment_completed()
                    if len(pdf_entries) > 0:
                        await self.progress_tracker.increment_pdfs(len(pdf_entries))
                    if not self.config.skip_images and page_data['data'].get('images'):
                        await self.progress_tracker.increment_images(len(page_data['data']['images']))
                    await self._send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if was_failed:
                        await self.job_state.decrement_failed()
                    await self.job_state.increment_completed()

                # Discover new URLs if in discovery mode
                if self.config.discovery_mode and not self.abort_crawl:
                    new_urls = await self.discover_urls(page_data['html_content'], url)
                    for new_url in new_urls:
                        if self.abort_crawl:
                            break
                        if urlparse(new_url).path.lower().endswith("piwik.php"):
                            continue
                        if new_url not in self.visited_urls and new_url not in self.to_visit:
                            self.to_visit.append(new_url)
                            self.url_depth[new_url] = self.url_depth.get(url, 0) + 1
                            self.url_source[new_url] = "discovery"

                            if self.url_tracking_manager:
                                sitemap_entry = self._lookup_sitemap_entry(new_url) or {}
                                await self.url_tracking_manager.add_url(
                                    new_url,
                                    source="discovery",
                                    sitemap_date=sitemap_entry.get("last_modified")
                                )
                            await self._update_total_urls(len(self.visited_urls) + len(self.to_visit))
            else:
                error_msg = "Extraction failed"

                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_failed(url, error_msg)
                if self.progress_tracker:
                    if not was_failed:
                        await self.progress_tracker.increment_failed()
                    await self.progress_tracker.increment_errors()
                    await self._send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if not was_failed:
                        await self.job_state.increment_failed()

                async with self.counter_lock:
                    self.page_counter -= 1

    async def _run_crawl_batches(self, crawler: AsyncWebCrawler):
        """Process crawl batches for the current to_visit list."""
        while self.to_visit and not self.abort_crawl and (
            self.config.max_pages == 0
            or self.page_counter < self.config.max_pages
            or self.allow_over_max_pages
        ):
            if time.monotonic() - self.browser_last_restart >= self.browser_restart_interval_seconds:
                print("Restarting browser: reached hourly restart interval")
                self.restart_crawler = True
                break
            batch_size = min(self.config.max_concurrency, len(self.to_visit))
            batch = self.to_visit[:batch_size]
            self.to_visit = self.to_visit[batch_size:]

            tasks = [self.crawl_page(url, crawler) for url in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.abort_crawl:
                break
            if self.restart_crawler:
                break

    async def crawl(self) -> Dict:
        """Main crawl method"""
        try:
            if self.http_session is None or self.http_session.closed:
                connector = aiohttp.TCPConnector(
                    limit=self.config.max_concurrency,
                    limit_per_host=self.config.max_concurrency
                )
                self.http_session = aiohttp.ClientSession(
                    headers=self.headers,
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=120)
                )

            await self._run_sitemap_scrape()
            await self.setup_directories()

            if self.url_tracking_manager:
                await self.url_tracking_manager.initialize()
                removed = await self.url_tracking_manager.purge_forbidden_hosts(
                    list(self._get_forbidden_hosts())
                )
                if removed:
                    print(f"Removed {removed} forbidden URLs from tracking state")
            if self.progress_tracker:
                await self.progress_tracker.start()

            resume_urls: List[str] = []
            resume_current_url: Optional[str] = None
            completed_count = 0
            if self.url_tracking_manager:
                tracked = await self.url_tracking_manager.get_all_urls()
                if tracked:
                    for url, meta in tracked.items():
                        if self._is_forbidden_host((urlparse(url).hostname or "").lower()):
                            continue
                        status = (meta or {}).get("status")
                        if status in ("pending", "failed", "processing"):
                            resume_urls.append(url)
                        elif status in ("completed",):
                            self.visited_urls.add(url)
                            completed_count += 1
                    if self.job_state:
                        snapshot = await self.job_state.get_snapshot()
                        resume_current_url = snapshot.current_url
                    if resume_current_url in resume_urls:
                        resume_urls.remove(resume_current_url)
                        resume_urls.insert(0, resume_current_url)

            if self.job_state:
                await self.job_state.set_status("running")

            if self.progress_tracker:
                await self.progress_tracker.set_stage("initialization")
            await self._send_stage(Stage.INITIALIZATION)

            start_url = str(self.config.url)
            print(f"Crawl for {start_url}")
            if resume_urls:
                self.to_visit = resume_urls
                for u in self.to_visit:
                    self.url_depth[u] = 0
                    self.url_source[u] = "rescrape_failed" if self.config.rescrape_failed else "resume"
                if completed_count:
                    self.page_counter = completed_count

                await self._update_total_urls(completed_count + len(self.to_visit))

                print(f"Resuming job {self.job_id}: {len(self.to_visit)} URLs remaining")
            if not resume_urls and await self.is_sitemap(start_url):
                print(f"Detected sitemap: {start_url}")
                urls = await self.parse_sitemap(start_url)

                await self._send_stage(Stage.SITEMAP_DETECTED, {"sitemap_url": start_url, "total_urls": len(urls)})

                urls_to_crawl = urls[:self.config.max_pages] if self.config.max_pages > 0 else urls
                self.to_visit = urls_to_crawl
                for u in self.to_visit:
                    self.url_depth[u] = 0
                    self.url_source[u] = "sitemap"
                print(f"Found {len(urls)} URLs in sitemap, will crawl {len(self.to_visit)}")

                await self._send_stage(Stage.URLS_DISCOVERED, {"discovered": len(urls), "total_to_crawl": len(self.to_visit)})
                if self.job_state:
                    await self.job_state.set_total_urls(len(self.to_visit))
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(len(self.to_visit))
            elif not resume_urls and not self.config.rescrape_failed:
                self.to_visit = [start_url]
                self.url_depth[start_url] = 0
                self.url_source[start_url] = "seed"

                if self.url_tracking_manager:
                    sitemap_entry = self._lookup_sitemap_entry(start_url) or {}
                    await self.url_tracking_manager.add_url(
                        start_url,
                        source="seed",
                        sitemap_date=sitemap_entry.get("last_modified")
                    )
                if self.job_state:
                    await self.job_state.set_total_urls(1)
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(1)

            total_to_crawl = len(self.to_visit) if not self.config.discovery_mode else self.config.max_pages
            await self._send_stage(Stage.CRAWLING_STARTED, {"total_to_crawl": total_to_crawl})

            if self.progress_tracker:
                await self.progress_tracker.set_stage("scraping")
            await self._send_stage(Stage.CRAWLING_STARTED)

            browser_config = BrowserConfig(
                headless=True,
                verbose=False
            )

            while True:
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    self.browser_last_restart = time.monotonic()
                    await self._run_crawl_batches(crawler)
                    if self.abort_crawl:
                        raise RuntimeError(self.abort_reason or "Aborting crawl due to server error")
                    if not self.restart_crawler:
                        break

                async with self.restart_lock:
                    self.browser_restart_count += 1
                    restart_urls = list(self.restart_urls)
                    self.restart_urls.clear()
                    self.restart_crawler = False

                if self.browser_restart_count > self.max_browser_restarts:
                    raise RuntimeError("Aborting crawl: exceeded maximum browser restarts")

                for retry_url in restart_urls:
                    if retry_url not in self.to_visit:
                        self.to_visit.insert(0, retry_url)

                if self.config.rescrape_failed and self.url_tracking_manager:
                    failed_urls = await self.url_tracking_manager.get_urls_by_status(["failed"])
                    if len(failed_urls) > 1:
                        rescrape_round = 0
                        max_rescrape_rounds = 10
                        while failed_urls and rescrape_round < max_rescrape_rounds:
                            rescrape_round += 1
                            print(f"Rescrape round {rescrape_round}: retrying {len(failed_urls)} failed URLs")

                            for failed_url in failed_urls:
                                self.visited_urls.discard(failed_url)
                                self.url_depth[failed_url] = 0
                                self.url_source[failed_url] = "rescrape_failed"

                            self.to_visit = failed_urls
                            self.allow_over_max_pages = True
                            await self._run_crawl_batches(crawler)
                            failed_urls = await self.url_tracking_manager.get_urls_by_status(["failed"])

                        self.allow_over_max_pages = False

            if self.progress_tracker:
                await self.progress_tracker.set_stage("completed")
            await self._send_stage(Stage.COMPLETED)
            if self.progress_tracker:
                await self.progress_tracker.stop()

                summary_data = await self.progress_tracker.get_summary()
                if self.summary_manager:
                    formatted_summary = SummaryManager.format_summary(
                        job_id=self.job_id,
                        stage="completed",
                        progress=summary_data,
                        output_directory=str(self.output_dir),
                        error=None
                    )
                    await self.summary_manager.save_summary(formatted_summary)
                    await self._send_summary(formatted_summary)

                    print("\n" + SummaryManager.format_text_summary(formatted_summary))
            if self.job_state:
                await self.job_state.set_status("completed")

            return {
                'pages_crawled': self.page_counter,
                'output_directory': str(self.output_dir),
                'label': self.config.label
            }

        except Exception as e:
            error_msg = str(e)
            print(f"Crawl job failed: {error_msg}")

            if self.progress_tracker:
                await self.progress_tracker.set_stage("failed")
            await self._send_stage(Stage.FAILED)
            if self.progress_tracker:
                await self.progress_tracker.stop()

                summary_data = await self.progress_tracker.get_summary()
                if self.summary_manager:
                    formatted_summary = SummaryManager.format_summary(
                        job_id=self.job_id,
                        stage="failed",
                        progress=summary_data,
                        output_directory=str(self.output_dir),
                        error=error_msg
                    )
                    await self.summary_manager.save_summary(formatted_summary)
                    await self._send_summary(formatted_summary)

                    print("\n" + SummaryManager.format_text_summary(formatted_summary))

            if self.job_state:
                await self.job_state.set_error(error_msg)

            raise
        finally:
            if self.http_session:
                await self.http_session.close()
                self.http_session = None
