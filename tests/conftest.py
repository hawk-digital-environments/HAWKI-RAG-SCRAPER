import sys
import types
from importlib.machinery import ModuleSpec
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

for path in (str(ROOT_DIR), str(SRC_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

for module_name in list(sys.modules):
    if module_name == "hawki_crawler" or module_name.startswith("hawki_crawler."):
        del sys.modules[module_name]

hawki_crawler = types.ModuleType("hawki_crawler")
hawki_crawler.__file__ = str(SRC_DIR / "__init__.py")
hawki_crawler.__path__ = [str(SRC_DIR)]
hawki_crawler.__package__ = "hawki_crawler"
hawki_crawler.__spec__ = ModuleSpec("hawki_crawler", loader=None, is_package=True)
sys.modules["hawki_crawler"] = hawki_crawler
