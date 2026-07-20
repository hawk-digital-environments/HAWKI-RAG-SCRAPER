import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", "/tmp/customcrawler-crawl4ai")

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
