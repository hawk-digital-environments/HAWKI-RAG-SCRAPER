import argparse
import asyncio
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CacheMode, CrawlerRunConfig
from bs4 import BeautifulSoup

from hawk_sitemap_scraper import _run_hawk_sitemap, _build_arg_parser


async def test_crawl():
    """Lightweight crawl test for manual debugging."""
    url = "https://www.hawki.info/roadmap"

    browser_config = BrowserConfig(headless=True, verbose=True)
    run_config = CrawlerRunConfig(
        word_count_threshold=1,
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        page_timeout=60000,
        delay_before_return_html=2.0,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

        print(f"Crawl success: {result.success}")
        print(f"Markdown length: {len(result.markdown) if result.markdown else 0}")
        print(f"HTML length: {len(result.html) if result.html else 0}")
        print("\n=== First 3000 chars of HTML ===")
        print(result.html[:3000] if result.html else "NO HTML")

        print("\n=== Trying BeautifulSoup extraction ===")
        soup = BeautifulSoup(result.html, "html.parser")

        main_content = soup.find("main") or soup.find("article") or soup.find("body")
        print(f"Found element: {main_content.name if main_content else 'None'}")

        if main_content:
            for script in main_content(["script", "style", "nav", "header", "footer"]):
                script.decompose()

            text = main_content.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            clean_text = "\n\n".join(lines)

            print(f"\nExtracted text length: {len(clean_text)}")
            print(f"\nFirst 1000 chars of extracted text:")
            print(clean_text[:1000])

        print("\n=== Checking for images ===")
        img_tags = soup.find_all("img")
        print(f"Found {len(img_tags)} img tags")
        for i, img in enumerate(img_tags[:5]):
            print(f"  {i+1}. src={img.get('src', 'N/A')[:100]}")
            print(f"     data-src={img.get('data-src', 'N/A')[:100]}")


def main():
    parser = _build_arg_parser()
    parser.add_argument(
        "--debug-crawl",
        action="store_true",
        help="Run the legacy debug crawl instead of the sitemap scraper.",
    )
    args = parser.parse_args()

    if args.hawk_sitemap:
        asyncio.run(_run_hawk_sitemap(args))
    elif args.debug_crawl:
        asyncio.run(test_crawl())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
