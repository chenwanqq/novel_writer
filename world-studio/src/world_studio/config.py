"""Explicit data locations; never store user data in the installed plugin."""
import os
from pathlib import Path


def data_path(value: str | Path | None = None) -> Path:
    configured = value or os.environ.get("WORLD_STUDIO_DATA")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".local/share/world-studio"


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the configured data directory")
    return path
