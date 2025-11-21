# import asyncio
# from crawl4ai import AsyncWebCrawler

# async def main():
#     async with AsyncWebCrawler() as crawler:
#         result = await crawler.arun("https://projekte.g.hawk.de/projekt/67a084b080f87")
#         print(result.markdown)  # Print first 300 chars

# if __name__ == "__main__":
#     asyncio.run(main())


import asyncio
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode

async def main():
    browser_config = BrowserConfig(verbose=True)
    run_config = CrawlerRunConfig(
        # Content filtering
        word_count_threshold=10,
        excluded_tags=['form', 'header'],
        exclude_external_links=True,

        # Content processing
        process_iframes=True,
        remove_overlay_elements=True,

        # Cache control
        cache_mode=CacheMode.ENABLED  # Use cache if available
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url="https://hawki.info",
            config=run_config
        )

        if result.success:
            # Print clean content
            print("Content:", result.markdown[:500])  # First 500 chars

            # Process images
            for image in result.media["images"]:
                print(f"Found image: {image['src']}")

            # Process links
            for link in result.links["internal"]:
                print(f"Internal link: {link['href']}")

        else:
            print(f"Crawl failed: {result.error_message}")

if __name__ == "__main__":
    asyncio.run(main())