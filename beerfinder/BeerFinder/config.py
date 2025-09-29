from pathlib import Path
import yaml

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
META_DIR = DATA_DIR / "meta"

def ensure_dirs(path):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

def load_yaml(path: str | Path) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


