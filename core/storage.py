"""Atomic, user-scoped campaign persistence for Reaction Racer."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import secrets
import threading
import uuid
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_FILE = 'campaign.json'
SNAPSHOT_FILE = 'ax_snapshot.json'
PROFILE_FILE = 'profile.json'
WORKSPACE_FILE = 'workspace.json'
_LOCK = threading.RLock()
_USERNAME_RE = re.compile(r'^[^\x00-\x1f/\\]{1,32}$')


def data_dir() -> Path:
    if getattr(sys, 'frozen', False):  # PyInstaller bundle
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    directory = base / 'data'
    directory.mkdir(parents=True, exist_ok=True)
    return directory

def storage_secret() -> str:
    """Stable local key used to sign the username stored in NiceGUI sessions."""
    path = data_dir() / '.storage_secret'
    if not path.exists():
        _atomic_write(path, secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip()



def normalize_username(raw: str) -> str:
    username = ' '.join(str(raw or '').strip().split())
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError('Username must be 1–32 characters and contain no slashes.')
    return username


def user_key(username: str) -> str:
    """Opaque filesystem key; usernames remain case-insensitive identities."""
    return hashlib.sha256(normalize_username(username).casefold().encode()).hexdigest()[:24]


def user_dir(username: str, *, create: bool = False) -> Path:
    path = data_dir() / 'users' / user_key(username)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_exists(username: str) -> bool:
    return (user_dir(username) / PROFILE_FILE).exists()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, temporary = tempfile.mkstemp(
            prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
        try:
            with open(fd, 'w') as stream:
                stream.write(text)
                stream.flush()
            Path(temporary).replace(target)  # atomic rename (os.replace semantics)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise


def _load_quarantining(path: Path) -> dict[str, Any] | None:
    """Parse JSON; on corruption keep the file as evidence and return None."""
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else None
    except (json.JSONDecodeError, OSError):
        path.rename(path.with_suffix(path.suffix + '.corrupt'))
        return None


def _adopt_legacy_campaign(username: str) -> None:
    """Assign the pre-login shared campaign to the first account created."""
    legacy_config = data_dir() / CONFIG_FILE
    legacy_snapshot = data_dir() / SNAPSHOT_FILE
    if not legacy_config.exists() or not legacy_snapshot.exists():
        return
    campaign_id = f'legacy-{uuid.uuid4().hex[:10]}'
    target = user_dir(username, create=True) / 'campaigns' / campaign_id
    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(legacy_config, target / CONFIG_FILE)
        shutil.copy2(legacy_snapshot, target / SNAPSHOT_FILE)
        _atomic_write(user_dir(username) / WORKSPACE_FILE,
                      json.dumps({'active_campaign': campaign_id}))
        legacy_config.unlink()
        legacy_snapshot.unlink()
    except OSError:
        # Keep the legacy files available if a migration cannot complete.
        shutil.rmtree(target, ignore_errors=True)
        return


def create_user(raw_username: str) -> tuple[str, bool]:
    """Create or find a username workspace, returning ``(username, created)``."""
    username = normalize_username(raw_username)
    with _LOCK:
        if user_exists(username):
            return str(profile(username).get('username') or username), False
        directory = user_dir(username, create=True)
        _atomic_write(directory / PROFILE_FILE,
                      json.dumps({'username': username, 'created_at': _now()}, indent=2))
        _atomic_write(directory / WORKSPACE_FILE,
                      json.dumps({'active_campaign': None}, indent=2))
        _adopt_legacy_campaign(username)
        return username, True


def profile(username: str) -> dict[str, Any]:
    return _load_quarantining(user_dir(username) / PROFILE_FILE) or {}


def active_campaign_id(username: str) -> str | None:
    workspace = _load_quarantining(user_dir(username) / WORKSPACE_FILE) or {}
    value = workspace.get('active_campaign')
    return value if isinstance(value, str) and value else None


def set_active_campaign(username: str, campaign_id: str) -> None:
    _atomic_write(user_dir(username) / WORKSPACE_FILE,
                  json.dumps({'active_campaign': campaign_id}, indent=2))


def new_campaign_id() -> str:
    return f'{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}'


def campaign_dir(username: str, campaign_id: str) -> Path:
    if not campaign_id or '/' in campaign_id or '\\' in campaign_id:
        raise ValueError('Invalid campaign id.')
    return user_dir(username) / 'campaigns' / campaign_id


def config_path(username: str, campaign_id: str) -> Path:
    return campaign_dir(username, campaign_id) / CONFIG_FILE


def snapshot_path(username: str, campaign_id: str) -> Path:
    return campaign_dir(username, campaign_id) / SNAPSHOT_FILE


def save(username: str, campaign_id: str, payload: dict[str, Any]) -> None:
    _atomic_write(config_path(username, campaign_id), json.dumps(payload, indent=2))


def load(username: str, campaign_id: str) -> dict[str, Any] | None:
    return _load_quarantining(config_path(username, campaign_id))


def load_snapshot(username: str, campaign_id: str) -> dict[str, Any] | None:
    return _load_quarantining(snapshot_path(username, campaign_id))


def clear(username: str, campaign_id: str) -> None:
    config_path(username, campaign_id).unlink(missing_ok=True)
    snapshot_path(username, campaign_id).unlink(missing_ok=True)


def list_campaigns(username: str) -> list[dict[str, Any]]:
    """Return campaign summaries ordered by most recent update."""
    root = user_dir(username) / 'campaigns'
    if not root.exists():
        return []
    active = active_campaign_id(username)
    result: list[dict[str, Any]] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        payload = _load_quarantining(directory / CONFIG_FILE)
        if not payload:
            continue
        config = payload.get('config') or {}
        result.append({
            'id': directory.name,
            'name': str(config.get('name') or directory.name),
            'finished': bool(payload.get('finished', False)),
            'completed': int(payload.get('completed', 0) or 0),
            'running': int(payload.get('running', 0) or 0),
            'created_at': str(payload.get('created_at') or ''),
            'updated_at': str(payload.get('updated_at') or ''),
            'active': directory.name == active,
        })
    result.sort(key=lambda item: item['updated_at'] or item['created_at'], reverse=True)
    return result
