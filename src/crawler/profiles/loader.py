from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse


def load_site_profile(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _repo_profile_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "profiles"


def _host_matches(host: str, pattern: str) -> bool:
    host = (host or "").lower()
    pattern = (pattern or "").lower()
    if not host or not pattern:
        return False
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    return host == pattern or host.endswith(f".{pattern}")


def resolve_site_profile(url: str, explicit_path: Optional[str] = None) -> Dict[str, Any]:
    if explicit_path:
        return load_site_profile(Path(explicit_path))

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return {}

    profile_dir = _repo_profile_dir()
    if not profile_dir.exists():
        return {}

    for candidate in sorted(profile_dir.glob("*.json")):
        profile = load_site_profile(candidate)
        match_hosts = profile.get("match_hosts") or []
        if any(_host_matches(host, pattern) for pattern in match_hosts):
            profile.setdefault("_profile_path", str(candidate))
            return profile
    return {}
