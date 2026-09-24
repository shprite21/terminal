from pathlib import Path
import importlib.metadata
import platform
from .storage import digest


def lab_fingerprint():
    root = Path(__file__).parent
    files = {name: digest((root/name).read_bytes()) for name in
             ["lab_data.py", "bar_lab.py", "market_making.py", "models.py", "storage.py"]}
    return {"python": platform.python_version(), "source_hashes": files,
            "dependencies": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "pydantic", "yfinance"]}}
