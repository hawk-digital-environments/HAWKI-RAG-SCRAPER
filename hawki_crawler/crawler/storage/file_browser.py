import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileBrowser:
    """Lists and resolves files inside a crawl job directory."""

    def __init__(self, *, job_dir: Path) -> None:
        self.job_dir = job_dir

    def list_files(self, relative: bool = True) -> List[str]:
        files = []

        if not self.job_dir.exists():
            return files

        for root, _dirs, filenames in os.walk(self.job_dir):
            for filename in filenames:
                filepath = Path(root) / filename

                if relative:
                    rel_path = filepath.relative_to(self.job_dir)
                    files.append(str(rel_path))
                else:
                    files.append(str(filepath))

        return sorted(files)

    def get_file_path(self, relative_path: str) -> Optional[Path]:
        filepath = self.job_dir / relative_path

        try:
            filepath = filepath.resolve()
            if not filepath.is_relative_to(self.job_dir.resolve()):
                return None
        except Exception:
            return None

        if filepath.exists() and filepath.is_file():
            return filepath

        return None

    def get_file_info(self, relative_path: str) -> Optional[Dict[str, Any]]:
        filepath = self.get_file_path(relative_path)

        if not filepath:
            return None

        stat = filepath.stat()

        return {
            "name": filepath.name,
            "path": relative_path,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "type": self.get_file_type(filepath),
        }

    @staticmethod
    def get_file_type(filepath: Path) -> str:
        suffix = filepath.suffix.lower()

        type_map = {
            ".json": "application/json",
            ".md": "text/markdown",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".txt": "text/plain",
            ".html": "text/html",
            ".pdf": "application/pdf",
        }

        return type_map.get(suffix, "application/octet-stream")
