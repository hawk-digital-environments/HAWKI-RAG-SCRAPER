import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", text) if t]


def _simhash(tokens: List[str]) -> int:
    if not tokens:
        return 0
    bits = [0] * 64
    for token in tokens:
        h = hashlib.md5(token.encode("utf-8")).digest()
        value = int.from_bytes(h[:8], "big")
        for i in range(64):
            bits[i] += 1 if (value >> i) & 1 else -1
    result = 0
    for i, score in enumerate(bits):
        if score > 0:
            result |= 1 << i
    return result


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _content_similarity(path_a: Path, path_b: Path) -> float:
    a = _normalize_text(_read_text(path_a))
    b = _normalize_text(_read_text(path_b))
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _folder_manifest_hash(folder: Path) -> str:
    entries: List[Tuple[str, str]] = []
    for file_path in sorted(folder.rglob("*")):
        if file_path.is_dir():
            continue
        rel = file_path.relative_to(folder).as_posix()
        entries.append((rel, _hash_file(file_path)))
    payload = json.dumps(entries, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iter_content_files(job_dir: Path) -> List[Path]:
    files: List[Path] = []
    for path in job_dir.rglob("content.md"):
        if "url_chunks" in path.parts:
            continue
        if "sitemaps" in path.parts:
            continue
        files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Find near-duplicate content.md files.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--base-path", default="/app/shared")
    parser.add_argument("--threshold", type=float, default=0.95)
    parser.add_argument("--dedupe-identical", action="store_true")
    args = parser.parse_args()

    job_dir = Path(args.base_path) / args.job_id
    if not job_dir.exists():
        raise SystemExit(f"Job directory not found: {job_dir}")

    content_files = _iter_content_files(job_dir)
    records = []
    for path in content_files:
        text = _read_text(path)
        normalized = _normalize_text(text)
        tokens = _tokenize(normalized)
        simhash = _simhash(tokens)
        records.append(
            {
                "content_path": path,
                "folder_path": path.parent,
                "simhash": simhash,
                "word_count": len(tokens),
                "content_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            }
        )

    bands = 4
    band_bits = 64 // bands
    buckets: List[Dict[int, List[int]]] = [{} for _ in range(bands)]
    for idx, rec in enumerate(records):
        simhash = rec["simhash"]
        for band in range(bands):
            key = (simhash >> (band * band_bits)) & ((1 << band_bits) - 1)
            buckets[band].setdefault(key, []).append(idx)

    candidate_pairs = set()
    for bucket in buckets:
        for ids in bucket.values():
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pair = (ids[i], ids[j])
                    candidate_pairs.add(pair)

    similar_pairs = []
    for i, j in candidate_pairs:
        a = records[i]
        b = records[j]
        simhash_similarity = 1.0 - (_hamming_distance(a["simhash"], b["simhash"]) / 64.0)
        if simhash_similarity < args.threshold:
            continue
        seq_similarity = _content_similarity(a["content_path"], b["content_path"])
        if seq_similarity >= args.threshold:
            similar_pairs.append((i, j, seq_similarity))

    parent = list(range(len(records)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for i, j, _ in similar_pairs:
        union(i, j)

    groups: Dict[int, List[int]] = {}
    for idx in range(len(records)):
        root = find(idx)
        groups.setdefault(root, []).append(idx)

    similar_groups = []
    for members in groups.values():
        if len(members) < 2:
            continue
        folders = [str(records[i]["folder_path"]) for i in members]
        similar_groups.append({"folders": sorted(folders)})

    exact_groups: Dict[str, List[str]] = {}
    for rec in records:
        exact_groups.setdefault(rec["content_hash"], []).append(str(rec["folder_path"]))
    exact_content_duplicates = [
        {"content_hash": h, "folders": sorted(folders)}
        for h, folders in exact_groups.items()
        if len(folders) > 1
    ]

    manifest_groups: Dict[str, List[str]] = {}
    for rec in records:
        folder = Path(rec["folder_path"])
        manifest_hash = _folder_manifest_hash(folder)
        manifest_groups.setdefault(manifest_hash, []).append(str(folder))

    identical_folder_groups = [
        {"manifest_hash": h, "folders": sorted(folders)}
        for h, folders in manifest_groups.items()
        if len(folders) > 1
    ]

    removed = []
    if args.dedupe_identical:
        for group in identical_folder_groups:
            folders = group["folders"]
            keep = folders[0]
            for path in folders[1:]:
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path)

    output = {
        "job_id": args.job_id,
        "threshold": args.threshold,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_files": len(records),
        "candidates_checked": len(candidate_pairs),
        "similar_groups": similar_groups,
        "exact_content_duplicates": exact_content_duplicates,
        "identical_folder_groups": identical_folder_groups,
        "dedupe_removed": removed,
    }

    output_path = job_dir / "folder_processing.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
