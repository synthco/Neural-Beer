from pathlib import Path
import yaml

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
META_DIR = DATA_DIR / "meta"


def ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)


def load_yaml(path: str | Path) -> dict:
    """Load YAML from a path.

    Tries the provided path first. If it does not exist and the path is
    relative, also tries resolving it relative to the package root
    (two levels up from this file), which allows using paths like
    "configs/classes.yaml" regardless of the current working directory.
    """
    p = Path(path)
    # Try as-is if it exists
    if p.exists():
        with p.open("r") as f:
            return yaml.safe_load(f) or {}

    # Fallback: resolve relative to the package root (…/beerfinder)
    if not p.is_absolute():
        pkg_root = Path(__file__).resolve().parent.parent
        alt = pkg_root / p
        if alt.exists():
            with alt.open("r") as f:
                return yaml.safe_load(f) or {}

    # If still not found, raise a clearer error
        raise FileNotFoundError(f"YAML file not found: {p} (also tried relative to {pkg_root if not p.is_absolute() else 'N/A'})")


