"""Atomic JSON persistence for the shared campaign (frozen-app aware)."""

import json
import sys
from pathlib import Path
from typing import Any

CONFIG_FILE = 'campaign.json'
SNAPSHOT_FILE = 'ax_snapshot.json'


def data_dir() -> Path:
    if getattr(sys, 'frozen', False):  # PyInstaller bundle
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    directory = base / 'data'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path() -> Path:
    return data_dir() / CONFIG_FILE


def snapshot_path() -> Path:
    return data_dir() / SNAPSHOT_FILE


def _atomic_write(target: Path, text: str) -> None:
    tmp = target.with_suffix(target.suffix + '.tmp')
    tmp.write_text(text)
    tmp.replace(target)  # atomic rename (os.replace semantics)


def save(payload: dict[str, Any]) -> None:
    _atomic_write(config_path(), json.dumps(payload, indent=2))


def _load_quarantining(path: Path) -> dict[str, Any] | None:
    """Parse JSON; on corruption keep the file as evidence and return None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        path.rename(path.with_suffix(path.suffix + '.corrupt'))
        return None


def load() -> dict[str, Any] | None:
    return _load_quarantining(config_path())


def load_snapshot() -> dict[str, Any] | None:
    return _load_quarantining(snapshot_path())


def clear() -> None:
    config_path().unlink(missing_ok=True)
    snapshot_path().unlink(missing_ok=True)
