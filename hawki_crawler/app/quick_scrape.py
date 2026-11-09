import os
from typing import Dict
from urllib.parse import urljoin

import html2text
from bs4 import BeautifulSoup
from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig

from hawki_crawler.runtime.browser import SafeBrowser as AsyncWebCrawler


async def extract_page_content(url: str, skip_images: bool = False, date_selector: str = None) -> Dict:
    """
    Temporary extraction function for quick scraping without storage.

    This function:
    - Fetches and renders the page using crawl4ai
    - Extracts content, images, title, and metadata
    - Returns data directly without saving to disk

    Args:
        url: URL to scrape
        skip_images: Whether to skip image extraction
        date_selector: Optional CSS selector for date extraction

    Returns:
        Dictionary with extracted data
    """
    browser_config = BrowserConfig(
        headless=True,
        verbose=False
    )

    wait_until = os.getenv("CRAWL_WAIT_UNTIL", "domcontentloaded")
    page_timeout_ms = int(os.getenv("CRAWL_PAGE_TIMEOUT_MS", "90000"))

    run_config = CrawlerRunConfig(
        word_count_threshold=0,  # No threshold - capture all content
        exclude_external_links=False,
        process_iframes=False,
        remove_overlay_elements=True,
        cache_mode=CacheMode.BYPASS,
        wait_until=wait_until,
        page_timeout=page_timeout_ms,
        delay_before_return_html=5.0
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            raise Exception(f"Failed to crawl {url}: {result.error_message}")

        # Extract markdown content (with fallbacks)
        markdown_content = result.markdown

        if not markdown_content or len(markdown_content.strip()) <= 1:
            # Try html2text first
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            h.ignore_images = False
            markdown_content = h.handle(result.html)

            # If html2text also fails, use BeautifulSoup
            if not markdown_content or len(markdown_content.strip()) <= 1:
                html_to_parse = result.fit_html if hasattr(result, 'fit_html') and result.fit_html else \
                              result.cleaned_html if hasattr(result, 'cleaned_html') and result.cleaned_html else \
                              result.html
                soup_temp = BeautifulSoup(html_to_parse, 'html.parser')

                main_content = soup_temp.find('main') or soup_temp.find('article') or soup_temp.find('body')
                if main_content:
                    for script in main_content(['script', 'style', 'nav', 'header', 'footer']):
                        script.decompose()

                    markdown_content = main_content.get_text(separator='\n', strip=True)
                    lines = [line.strip() for line in markdown_content.split('\n') if line.strip()]
                    markdown_content = '\n\n'.join(lines)

        # Parse HTML for additional data
        soup = BeautifulSoup(result.html, 'html.parser')

        # Extract title
        title = None
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.text.strip()

        # Extract meta image
        meta_img_url = None
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            meta_img_url = og_image['content']

        # Extract date if selector provided
        date_text = None
        if date_selector:
            date_elements = soup.select(date_selector)
            for elem in date_elements:
                date_text = elem.get('content') or elem.get('datetime') or elem.text
                if date_text:
                    date_text = date_text.strip()
                    break

        # Extract images (URLs only, no download)
        images = []
        if not skip_images:
            # Try crawl4ai's media extraction
            for img in (result.media or {}).get('images', []):
                img_src = img.get('src', '')
                if img_src:
                    absolute_img_url = urljoin(url, img_src)
                    images.append(absolute_img_url)

            # If crawl4ai found no images, fallback to BeautifulSoup
            if len(images) == 0:
                img_tags = soup.find_all('img')
                for img_tag in img_tags:
                    img_src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src')
                    if img_src and img_src.startswith(('http', '/')):
                        if not img_src.startswith('data:'):
                            absolute_img_url = urljoin(url, img_src)
                            if absolute_img_url not in images:
                                images.append(absolute_img_url)

        return {
            'title': title,
            'content': markdown_content if markdown_content else "",
            'images': images,
            'meta_image': meta_img_url,
            'date': date_text
        }
