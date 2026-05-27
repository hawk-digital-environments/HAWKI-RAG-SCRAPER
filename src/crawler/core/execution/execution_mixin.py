import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, List, TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig

from hawki_crawler.crawler.communication.interface import Stage
from hawki_crawler.crawler.core.execution.summary import finalize_crawl_summary
from hawki_crawler.crawler.storage.url_tracking_manager import generate_url_hash
from hawki_crawler.crawler.storage.page_output import build_page_metadata

if TYPE_CHECKING:
    from hawki_crawler.crawler.core.protocols import ServiceCrawlExecutionMixinProtocol


class ServiceCrawlExecutionMixin:
    """Main crawl workflow for one crawler job.

    This mixin owns the high-level crawl loop: pick URLs, crawl or download
    them, update progress/state, discover new URLs, and finish or fail the job.
    It expects the final CrawlerService class to provide shared state such as
    config, queues, trackers, storage, logging, and helper methods.
    """

    def _is_pause_requested(self: "ServiceCrawlExecutionMixinProtocol") -> bool:
        """Return True when the API has asked this job to pause."""
        return bool(self.pause_event and not self.pause_event.is_set())

    async def _wait_if_paused(self: "ServiceCrawlExecutionMixinProtocol") -> None:
        """Wait while the job is paused, without losing queued URLs.

        Pause is cooperative: active network/browser work is allowed to finish,
        then the crawler waits here before taking more URLs from the queue.
        """
        if not self._is_pause_requested():
            return

        if not self.pause_logged:
            self.job_logger.info("Crawl paused")
            self.pause_logged = True
            if self.job_state:
                await self.job_state.set_status("paused")

        while self._is_pause_requested() and not self.abort_crawl:
            await asyncio.sleep(1)

        if self.pause_logged and not self.abort_crawl:
            self.job_logger.info("Crawl resumed")
            self.pause_logged = False
            if self.job_state:
                await self.job_state.set_status("running")

    async def crawl_page(
        self: "ServiceCrawlExecutionMixinProtocol",
        url: str,
        crawl_result: Optional[object] = None
    ):
        """Process one URL and update all job state around it.

        Depending on the URL/resource type, this may skip the URL, download a
        PDF/file directly, render an HTML page with crawl4ai, save output, mark
        success/failure, and optionally discover more URLs.
        """
        async with self.semaphore:
            await self._wait_if_paused()
            if self.abort_crawl:
                return

            was_failed = False
            if self.url_tracking_manager:
                prior_state = await self.url_tracking_manager.get_url_state(url)
                was_failed = (prior_state or {}).get("status") == "failed"

            parsed_url = urlparse(url)
            if parsed_url.scheme not in ("http", "https"):
                self.job_logger.info("Skipping non-HTTP URL: %s", url)
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
                    await self.send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if was_failed:
                        await self.job_state.decrement_failed()
                    await self.job_state.increment_completed()
                return

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

            url_hash = generate_url_hash(url)

            if self.config.max_pages > 0:
                self.job_logger.info(
                    "Crawling [%s/%s]: %s",
                    current_page_number,
                    self.config.max_pages,
                    url,
                )
            else:
                self.job_logger.info("Crawling [%s/unlimited]: %s", current_page_number, url)

            if self.url_tracking_manager:
                await self.url_tracking_manager.set_processing(url, current_page_number)
            if self.progress_tracker:
                await self.progress_tracker.set_current_url(url)
            if self.job_state:
                await self.job_state.set_current_url(url)

            if self.url_policy.is_video_url(url):
                self.job_logger.info("Skipping video URL: %s", url)
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_completed(url, None)
                if self.progress_tracker:
                    if was_failed:
                        await self.progress_tracker.decrement_failed()
                    await self.progress_tracker.increment_completed()
                    await self.send_report_progress(await self.progress_tracker.get_progress())
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
                await self.trigger_safe_stop(error_msg)
                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_failed(url, error_msg)
                if self.progress_tracker:
                    if not was_failed:
                        await self.progress_tracker.increment_failed()
                    await self.progress_tracker.increment_errors()
                    await self.send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if not was_failed:
                        await self.job_state.increment_failed()
                async with self.counter_lock:
                    self.page_counter -= 1
                return

            page_data = None
            if await self.is_pdf_resource(url, head_status, head_headers):
                # Direct PDF URLs are saved as file metadata without rendering a page.
                pdf_entry = await self.fetch_and_save_pdf(
                    url,
                    current_page_number,
                    url_hash=url_hash,
                    page_url=url,
                )
                if pdf_entry:
                    pdf_lang = self.detect_language(None, head_headers, url=url)
                    sitemap_entry = self.lookup_sitemap_entry(url) or {}
                    fetched_at = datetime.now().isoformat()
                    updated_at = self.get_sitemap_date(sitemap_entry) or self.parse_http_date((head_headers or {}).get("last-modified"))
                    page_data = {
                        'data': build_page_metadata(
                            url=url,
                            source_url=url,
                            url_hash=url_hash,
                            title="",
                            lang=pdf_lang,
                            fetched_at=fetched_at,
                            published_at=self.get_sitemap_date(sitemap_entry),
                            updated_at=updated_at,
                            tags=[],
                            images=[],
                            pdfs=[pdf_entry],
                            files=[],
                            http_status=head_status,
                            content_length=None,
                            content_hash=None,
                            quality={},
                            markdown="",
                            low_quality_content=None,
                            source_type=self.url_source.get(url, 'seed'),
                            depth=self.url_depth.get(url, 0),
                        ),
                        'markdown': '',
                        'html_content': ''
                    }
            elif await self.is_file_resource(url, head_status, head_headers):
                # Office documents and other supported files are downloaded directly.
                file_entry = await self.fetch_and_save_file(
                    url,
                    current_page_number,
                    url_hash=url_hash,
                    page_url=url,
                )
                if file_entry:
                    file_lang = self.detect_language(None, head_headers, url=url)
                    sitemap_entry = self.lookup_sitemap_entry(url) or {}
                    fetched_at = datetime.now().isoformat()
                    updated_at = self.get_sitemap_date(sitemap_entry) or self.parse_http_date((head_headers or {}).get("last-modified"))
                    page_data = {
                        'data': build_page_metadata(
                            url=url,
                            source_url=url,
                            url_hash=url_hash,
                            title="",
                            lang=file_lang,
                            fetched_at=fetched_at,
                            published_at=self.get_sitemap_date(sitemap_entry),
                            updated_at=updated_at,
                            tags=[],
                            images=[],
                            pdfs=[],
                            files=[file_entry],
                            http_status=head_status,
                            content_length=None,
                            content_hash=None,
                            quality={},
                            markdown="",
                            low_quality_content=None,
                            source_type=self.url_source.get(url, 'seed'),
                            depth=self.url_depth.get(url, 0),
                        ),
                        'markdown': '',
                        'html_content': ''
                    }
            else:
                # HTML pages are rendered/extracted by crawl4ai.
                try:
                    page_data = await self.extract_page_data(
                        url,
                        current_page_number,
                        crawl_result=crawl_result,
                        head_headers=head_headers,
                        head_status=head_status,
                        depth=self.url_depth.get(url, 0),
                        source_type=self.url_source.get(url, 'seed'),
                        url_hash=url_hash,
                    )
                except RuntimeError as exc:
                    if str(exc).startswith("browser_closed:"):
                        self.job_logger.error("browser context closed for %s", url)
                        async with self.counter_lock:
                            self.page_counter -= 1
                            self.visited_urls.discard(url)
                        if self.url_tracking_manager:
                            await self.url_tracking_manager.set_failed(
                                url,
                                "browser context closed"
                            )
                        return
                    raise

            if page_data:
                # Save the page and any linked files discovered in its HTML.
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
                                    url_hash=url_hash,
                                    page_url=url,
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
                                    url_hash=url_hash,
                                    page_url=url,
                                )
                                if file_entry:
                                    file_entries.append(file_entry)

                page_data['data']['pdfs'] = pdf_entries
                page_data['data']['files'] = file_entries

                await self.save_page_data(page_data, current_page_number, url_hash)

                header_dates = None
                if head_headers:
                    header_dates = {
                        "last_modified": head_headers.get('last-modified'),
                        "date": head_headers.get('date')
                    }

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
                    await self.send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if was_failed:
                        await self.job_state.decrement_failed()
                    await self.job_state.increment_completed()

                if self.config.discovery_mode and not self.abort_crawl:
                    # Discovery mode grows the queue from links found on crawled pages.
                    new_urls = await self.discover_urls(page_data['html_content'], url)
                    for new_url in new_urls:
                        if self.abort_crawl:
                            break
                        new_url = self.url_policy.normalize_url(new_url)
                        if urlparse(new_url).path.lower().endswith("piwik.php"):
                            continue
                        if new_url not in self.visited_urls and new_url not in self.to_visit:
                            self.to_visit.append(new_url)
                            self.url_depth[new_url] = self.url_depth.get(url, 0) + 1
                            self.url_source[new_url] = "discovery"

                            if self.url_tracking_manager:
                                sitemap_entry = self.lookup_sitemap_entry(new_url) or {}
                                await self.url_tracking_manager.add_url(
                                    new_url,
                                    source="discovery",
                                    sitemap_date=self.get_sitemap_date(sitemap_entry)
                                )
                            await self.update_total_urls(len(self.visited_urls) + len(self.to_visit))
            else:
                # No usable page data means this URL failed, but the job can continue.
                error_msg = "Extraction failed"

                if self.url_tracking_manager:
                    await self.url_tracking_manager.set_failed(url, error_msg)
                if self.progress_tracker:
                    if not was_failed:
                        await self.progress_tracker.increment_failed()
                    await self.progress_tracker.increment_errors()
                    await self.send_report_progress(await self.progress_tracker.get_progress())
                if self.job_state:
                    if not was_failed:
                        await self.job_state.increment_failed()

                async with self.counter_lock:
                    self.page_counter -= 1

    async def _run_crawl_batches(self: "ServiceCrawlExecutionMixinProtocol", crawler: AsyncWebCrawler):
        """Drain the URL queue in batches until paused, stopped, or finished."""
        while self.to_visit and not self.abort_crawl and (
            self.config.max_pages == 0
            or self.page_counter < self.config.max_pages
            or self.allow_over_max_pages
        ):
            await self._wait_if_paused()
            if self.abort_crawl:
                break
            if self.enable_memory_watchdog:
                ratio = self.get_memory_usage_ratio()
                if ratio is not None and ratio >= self.memory_restart_threshold:
                    self.job_logger.error(
                        "memory watchdog triggered: usage %.1f%% >= %.1f%%",
                        ratio * 100,
                        self.memory_restart_threshold * 100,
                    )
                    self.restart_crawler = True
                    self.restart_reason = "memory"
                    break
            if (
                self.enable_browser_restarts
                and self.browser_restart_interval_seconds > 0
                and time.monotonic() - self.browser_last_restart >= self.browser_restart_interval_seconds
            ):
                self.job_logger.info("Restarting browser: reached hourly restart interval")
                self.restart_crawler = True
                break

            # Do not remove more URLs from the queue if a pause request arrived.
            batch_size = 1 if self._is_pause_requested() else min(self.config.max_concurrency, len(self.to_visit))
            batch = self.to_visit[:batch_size]
            self.to_visit = self.to_visit[batch_size:]

            if self._is_pause_requested():
                # Put the selected URL back so resume continues from the same place.
                self.to_visit = batch + self.to_visit
                await self._wait_if_paused()
                continue

            batch_html = [url for url in batch if not self.looks_like_file_url(url)]
            batch_direct = [url for url in batch if url not in batch_html]

            results_by_url = {}
            if batch_html:
                run_config = self.build_run_config()
                try:
                    results = await crawler.arun_many(batch_html, config=run_config)
                    if hasattr(results, "__aiter__"):
                        results = [r async for r in results]
                    for requested_url, result in zip(batch_html, results):
                        results_by_url.setdefault(requested_url, result)
                        for key in (
                            getattr(result, "url", None),
                            getattr(result, "page_url", None),
                            getattr(result, "final_url", None),
                        ):
                            if key:
                                results_by_url.setdefault(key, result)
                except Exception as exc:
                    self.job_logger.error("crawl4ai arun_many failed: %s", exc)

            tasks = [
                self.crawl_page(url, crawl_result=results_by_url.get(url))
                for url in batch_html
            ]
            tasks.extend(self.crawl_page(url) for url in batch_direct)
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.abort_crawl:
                break
            if self.restart_crawler:
                break

    async def crawl(self: "ServiceCrawlExecutionMixinProtocol") -> Dict:
        """Run the complete crawl job from initialization through final summary."""
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

            await self.run_sitemap_scrape()
            await self.setup_directories()

            # URL tracking lets cancelled/failed jobs resume from unfinished URLs.
            if self.url_tracking_manager:
                await self.url_tracking_manager.initialize()
                removed = await self.url_tracking_manager.purge_forbidden_hosts(
                    list(self.url_policy.get_forbidden_hosts())
                )
                if removed:
                    self.job_logger.info("Removed %s forbidden URLs from tracking state", removed)
            if self.progress_tracker:
                await self.progress_tracker.start()

            resume_urls: List[str] = []
            resume_current_url: Optional[str] = None
            completed_count = 0
            if self.url_tracking_manager:
                # Rebuild the in-memory queue from persisted URL state.
                tracked = await self.url_tracking_manager.get_all_urls()
                if tracked:
                    for url, meta in tracked.items():
                        if self.url_policy.is_forbidden_url(url):
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
            await self.send_stage(Stage.INITIALIZATION)

            start_url = str(self.config.url)
            sitemap_only = bool(getattr(self.config, "sitemap_only", False))
            if sitemap_only:
                self.config.discovery_mode = False
            self.job_logger.info("Crawl start for %s", start_url)
            if resume_urls:
                # Resume jobs prefer the URL that was current when the old run stopped.
                if sitemap_only:
                    resume_urls = [
                        url for url in resume_urls if self.lookup_sitemap_entry(url)
                    ]
                self.to_visit = resume_urls
                for u in self.to_visit:
                    self.url_depth[u] = 0
                    self.url_source[u] = "rescrape_failed" if self.config.rescrape_failed else "resume"
                if completed_count:
                    self.page_counter = completed_count

                await self.update_total_urls(completed_count + len(self.to_visit))

                self.job_logger.info(
                    "Resuming job %s: %s URLs remaining",
                    self.job_id,
                    len(self.to_visit),
                )
            if not resume_urls and await self.is_sitemap(start_url):
                # Sitemap entrypoint: parse the sitemap and seed the crawl queue.
                self.job_logger.info("Detected sitemap: %s", start_url)
                urls = await self.parse_sitemap(start_url)

                await self.send_stage(Stage.SITEMAP_DETECTED, {"sitemap_url": start_url, "total_urls": len(urls)})

                if sitemap_only:
                    urls_to_crawl = urls
                else:
                    urls_to_crawl = urls[:self.config.max_pages] if self.config.max_pages > 0 else urls
                self.to_visit = urls_to_crawl
                for u in self.to_visit:
                    self.url_depth[u] = 0
                    self.url_source[u] = "sitemap"
                self.job_logger.info(
                    "Found %s URLs in sitemap, will crawl %s",
                    len(urls),
                    len(self.to_visit),
                )

                await self.send_stage(Stage.URLS_DISCOVERED, {"discovered": len(urls), "total_to_crawl": len(self.to_visit)})
                if self.job_state:
                    await self.job_state.set_total_urls(len(self.to_visit))
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(len(self.to_visit))
            elif not resume_urls and getattr(self.config, "sitemap", False):
                # Profile-driven sitemap: use the already scraped sitemap file.
                sitemap_urls = list(getattr(self, "sitemap_urls", []) or [])
                if sitemap_urls:
                    if sitemap_only:
                        urls_to_crawl = sitemap_urls
                    else:
                        urls_to_crawl = sitemap_urls[:self.config.max_pages] if self.config.max_pages > 0 else sitemap_urls
                    self.to_visit = urls_to_crawl
                    for u in self.to_visit:
                        self.url_depth[u] = 0
                        self.url_source[u] = "sitemap"
                    self.job_logger.info(
                        "Loaded %s URLs from sitemap file, will crawl %s",
                        len(sitemap_urls),
                        len(self.to_visit),
                    )

                    await self.send_stage(
                        Stage.URLS_DISCOVERED,
                        {"discovered": len(sitemap_urls), "total_to_crawl": len(self.to_visit)}
                    )
                    if self.job_state:
                        await self.job_state.set_total_urls(len(self.to_visit))
                    if self.progress_tracker:
                        await self.progress_tracker.set_total_urls(len(self.to_visit))
            elif sitemap_only and not resume_urls:
                # Sitemap-only mode crawls only URLs that have sitemap metadata.
                sitemap_urls = list(self.sitemap_map.keys()) if self.sitemap_map else []
                if not sitemap_urls:
                    raise RuntimeError("Sitemap-only crawl requested but no sitemap URLs are available.")
                self.to_visit = sitemap_urls
                for u in self.to_visit:
                    self.url_depth[u] = 0
                    self.url_source[u] = "sitemap"
                self.job_logger.info("Sitemap-only crawl: will crawl %s URLs", len(self.to_visit))
                await self.send_stage(Stage.URLS_DISCOVERED, {"discovered": len(self.to_visit), "total_to_crawl": len(self.to_visit)})
                if self.job_state:
                    await self.job_state.set_total_urls(len(self.to_visit))
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(len(self.to_visit))
            elif not resume_urls and not self.config.rescrape_failed:
                self.to_visit = [start_url]
                self.url_depth[start_url] = 0
                self.url_source[start_url] = "seed"

                if self.url_tracking_manager:
                    sitemap_entry = self.lookup_sitemap_entry(start_url) or {}
                    await self.url_tracking_manager.add_url(
                        start_url,
                        source="seed",
                        sitemap_date=self.get_sitemap_date(sitemap_entry)
                    )
                if self.job_state:
                    await self.job_state.set_total_urls(1)
                if self.progress_tracker:
                    await self.progress_tracker.set_total_urls(1)

            total_to_crawl = len(self.to_visit) if not self.config.discovery_mode else self.config.max_pages
            await self.send_stage(Stage.CRAWLING_STARTED, {"total_to_crawl": total_to_crawl})

            if self.progress_tracker:
                await self.progress_tracker.set_stage("scraping")
            await self.send_stage(Stage.CRAWLING_STARTED)

            browser_config = BrowserConfig(
                headless=True,
                verbose=False
            )

            while True:
                # The browser can be restarted between batches if memory or browser health requires it.
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
                    restart_reason = self.restart_reason
                    self.restart_reason = None

                if (
                    restart_reason != "memory"
                    and self.enable_browser_restarts
                    and self.browser_restart_count > self.max_browser_restarts
                ):
                    raise RuntimeError("Aborting crawl: exceeded maximum browser restarts")

                if restart_reason == "memory":
                    await self.wait_for_memory_relief()

                for retry_url in restart_urls:
                    if self.url_policy.is_forbidden_url(retry_url):
                        continue
                    if retry_url not in self.to_visit:
                        self.to_visit.insert(0, retry_url)

                if self.config.rescrape_failed and self.url_tracking_manager:
                    # Optional cleanup pass: retry failed URLs for this job.
                    failed_urls = await self.url_tracking_manager.get_urls_by_status(["failed"])
                    failed_urls = [url for url in failed_urls if not self.url_policy.is_forbidden_url(url)]
                    if len(failed_urls) > 1:
                        rescrape_round = 0
                        max_rescrape_rounds = 10
                        while failed_urls and rescrape_round < max_rescrape_rounds:
                            rescrape_round += 1
                            self.job_logger.info(
                                "Rescrape round %s: retrying %s failed URLs",
                                rescrape_round,
                                len(failed_urls),
                            )

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
            await self.send_stage(Stage.COMPLETED)
            await finalize_crawl_summary(
                progress_tracker=self.progress_tracker,
                summary_manager=self.summary_manager,
                send_summary=self.send_summary,
                job_logger=self.job_logger,
                job_id=self.job_id,
                stage="completed",
                output_directory=self.output_dir,
                error=None,
            )
            if self.job_state:
                await self.job_state.set_status("completed")

            return {
                'pages_crawled': self.page_counter,
                'output_directory': str(self.output_dir),
                'label': self.config.label
            }

        except Exception as e:
            error_msg = str(e)
            self.job_logger.error("crawl exception: %s", error_msg, exc_info=True)
            self.job_logger.error("Crawl job failed: %s", error_msg)

            if self.progress_tracker:
                await self.progress_tracker.set_stage("failed")
            await self.send_stage(Stage.FAILED)
            await finalize_crawl_summary(
                progress_tracker=self.progress_tracker,
                summary_manager=self.summary_manager,
                send_summary=self.send_summary,
                job_logger=self.job_logger,
                job_id=self.job_id,
                stage="failed",
                output_directory=self.output_dir,
                error=error_msg,
            )

            if self.job_state:
                await self.job_state.set_error(error_msg)

            raise
        finally:
            if self.http_session:
                await self.http_session.close()
                self.http_session = None
