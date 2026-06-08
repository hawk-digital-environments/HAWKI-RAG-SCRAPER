import argparse
from pathlib import Path

from hawki_crawler.crawler.storage.page_output import validate_job_directory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a scraped dataset against the unified Markdown + JSON output contract."
    )
    parser.add_argument("job_dir", help="Path to the crawl job directory to validate.")
    args = parser.parse_args()

    job_dir = Path(args.job_dir)
    errors = validate_job_directory(job_dir)
    if errors:
        print("Dataset validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Dataset validation passed: {job_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
