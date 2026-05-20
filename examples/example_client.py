#!/usr/bin/env python3
"""
Example client for the Crawl4AI FastAPI service
Demonstrates how to submit crawl jobs and monitor their progress
"""

import requests
import time
import sys
import uuid
from typing import Optional


class CrawlClient:
    """Client for interacting with the Crawl4AI API"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')

    def submit_crawl(self, config: dict) -> Optional[dict]:
        """Submit a crawl job"""
        try:
            response = requests.post(f"{self.base_url}/crawl", json=config)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error submitting crawl job: {e}")
            return None

    def get_status(self, job_id: str) -> Optional[dict]:
        """Get the status of a crawl job"""
        try:
            response = requests.get(f"{self.base_url}/status/{job_id}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error getting job status: {e}")
            return None

    def list_jobs(self) -> Optional[dict]:
        """List all jobs"""
        try:
            response = requests.get(f"{self.base_url}/jobs")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error listing jobs: {e}")
            return None

    def wait_for_completion(self, job_id: str, poll_interval: int = 5) -> Optional[dict]:
        """Wait for a job to complete and return final status"""
        print(f"\nMonitoring job {job_id}...")
        print("-" * 60)

        while True:
            status = self.get_status(job_id)
            if not status:
                return None

            print(f"\rStatus: {status['status']:<12} | "
                  f"Pages: {status['pages_crawled']:<5} | "
                  f"Message: {status['message']:<30}", end='', flush=True)

            if status['status'] in ['completed', 'failed']:
                print()  # New line after completion
                return status

            time.sleep(poll_interval)


def example_sitemap_crawl():
    """Example: Crawl a sitemap with default settings"""
    print("\n" + "=" * 60)
    print("Example 1: Crawl a Sitemap")
    print("=" * 60)

    client = CrawlClient()

    job_id = str(uuid.uuid4())
    config = {
        "job_id": job_id,
        "url": "https://www.hawk.de/sitemaps/main/sitemap.xml",
        "max_pages": 1,
        "skip_images": True,
        "max_concurrency": 1,
        "max_rpm": 30
    }

    print(f"\nSubmitting crawl job for: {config['url']}")
    result = client.submit_crawl(config)

    if result:
        print(f"✓ Job submitted successfully!")
        print(f"Job ID: {job_id}")

        final_status = client.wait_for_completion(job_id)
        if final_status and final_status['status'] == 'completed':
            print(f"\n✓ Crawl completed successfully!")
            print(f"Output directory: {final_status['output_directory']}")
            print(f"Pages crawled: {final_status['pages_crawled']}")


def example_discovery_mode():
    """Example: Crawl with URL discovery mode"""
    print("\n" + "=" * 60)
    print("Example 2: URL Discovery Mode")
    print("=" * 60)

    client = CrawlClient()

    job_id = str(uuid.uuid4())
    config = {
        "job_id": job_id,
        "url": "https://example.com",
        "max_pages": 20,
        "discovery_mode": True,
        "skip_images": False,
        "date_selector": "time, .date, meta[property='og:updated_time']",
        "max_concurrency": 4,
        "max_rpm": 60
    }

    print(f"\nSubmitting crawl job for: {config['url']}")
    print("Discovery mode: Enabled")

    result = client.submit_crawl(config)

    if result:
        print(f"✓ Job submitted successfully!")
        print(f"Job ID: {job_id}")

        final_status = client.wait_for_completion(job_id)
        if final_status and final_status['status'] == 'completed':
            print(f"\n✓ Crawl completed successfully!")
            print(f"Output directory: {final_status['output_directory']}")
            print(f"Pages crawled: {final_status['pages_crawled']}")


def example_custom_rate_limiting():
    """Example: Custom rate limiting with image exclusions"""
    print("\n" + "=" * 60)
    print("Example 3: Custom Rate Limiting")
    print("=" * 60)

    client = CrawlClient()

    job_id = str(uuid.uuid4())
    config = {
        "job_id": job_id,
        "url": "https://news.ycombinator.com",
        "max_pages": 5,
        "request_delay": 3000,  # 3 seconds between requests
        "skip_images": False,
        "image_exceptions": ".header img, .footer img",
        "max_concurrency": 1  # Sequential crawling
    }

    print(f"\nSubmitting crawl job for: {config['url']}")
    print("Rate limiting: 3 seconds between requests")

    result = client.submit_crawl(config)

    if result:
        print(f"✓ Job submitted successfully!")
        print(f"Job ID: {job_id}")

        final_status = client.wait_for_completion(job_id)
        if final_status and final_status['status'] == 'completed':
            print(f"\n✓ Crawl completed successfully!")
            print(f"Output directory: {final_status['output_directory']}")
            print(f"Pages crawled: {final_status['pages_crawled']}")


def list_all_jobs():
    """List all jobs in the system"""
    print("\n" + "=" * 60)
    print("Listing All Jobs")
    print("=" * 60)

    client = CrawlClient()
    jobs = client.list_jobs()

    if jobs:
        print(f"\nTotal jobs: {jobs['total_jobs']}")
        if jobs['total_jobs'] > 0:
            print("\nJob Details:")
            print("-" * 60)
            for job_id, job_info in jobs['jobs'].items():
                print(f"\nJob ID: {job_id}")
                print(f"Status: {job_info['status']}")
                print(f"Message: {job_info['message']}")
                print(f"Pages crawled: {job_info['pages_crawled']}")
                if job_info.get('output_directory'):
                    print(f"Output: {job_info['output_directory']}")


def main():
    """Main function to run examples"""
    print("\n" + "=" * 60)
    print("Crawl4AI API Client Examples")
    print("=" * 60)

    if len(sys.argv) > 1:
        example = sys.argv[1]

        if example == "1":
            example_sitemap_crawl()
        elif example == "2":
            example_discovery_mode()
        elif example == "3":
            example_custom_rate_limiting()
        elif example == "list":
            list_all_jobs()
        else:
            print(f"\nUnknown example: {example}")
            print_usage()
    else:
        print("\nRunning all examples...")
        example_sitemap_crawl()
        time.sleep(2)
        example_discovery_mode()
        time.sleep(2)
        example_custom_rate_limiting()
        time.sleep(2)
        list_all_jobs()


def print_usage():
    """Print usage information"""
    print("\nUsage: python example_client.py [example_number|list]")
    print("\nExamples:")
    print("  1    - Crawl a sitemap")
    print("  2    - URL discovery mode")
    print("  3    - Custom rate limiting")
    print("  list - List all jobs")
    print("\nOr run without arguments to execute all examples")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
