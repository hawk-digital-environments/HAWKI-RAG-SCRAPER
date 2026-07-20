import argparse
import asyncio
import json
from pathlib import Path

from hawki_crawler.crawler.storage.storage_manager import StorageManager
from hawki_crawler.crawler.storage.page_output import METADATA_FILENAME, PAGE_ROOT_DIRNAME


async def rebuild_manifest(job_dir: Path) -> int:
    if not job_dir.exists():
        print(f"Job directory not found: {job_dir}")
        return 1

    storage = StorageManager(job_id=job_dir.name, base_path=str(job_dir.parent))
    pages_root = job_dir / PAGE_ROOT_DIRNAME
    metadata_files = sorted(pages_root.rglob(METADATA_FILENAME))
    if not metadata_files:
        print(f"No page metadata found under {pages_root}")
        return 1

    manifest_path = storage.get_completed_urls_manifest_path()
    if manifest_path.exists():
        manifest_path.unlink()

    completed = 0
    for metadata_file in metadata_files:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        url_hash = ((metadata.get("hashes") or {}).get("url_sha256"))
        await storage.upsert_completed_url_record(metadata, url_hash=url_hash)
        completed += 1

    print(f"Rebuilt completed manifest with {completed} records: {manifest_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild completed_urls.json for an existing crawl job directory."
    )
    parser.add_argument("job_dir", help="Path to the crawl job directory, e.g. /var/www/html/shared/Site_Test_20")
    args = parser.parse_args()
    return asyncio.run(rebuild_manifest(Path(args.job_dir)))


if __name__ == "__main__":
    raise SystemExit(main())
