"""Username sessions and per-user campaign selection."""

from __future__ import annotations

import threading
from typing import Any

from nicegui import app

from core import storage
from core.campaign import CampaignConfig, CampaignService

_lock = threading.RLock()
_services: dict[tuple[str, str], CampaignService] = {}


def current_username() -> str | None:
    value = app.storage.user.get('username')
    if not isinstance(value, str) or not value:
        return None
    try:
        return storage.normalize_username(value)
    except ValueError:
        return None


def login(raw_username: str) -> tuple[str, bool]:
    username, created = storage.create_user(raw_username)
    app.storage.user['username'] = username
    return username, created


def logout() -> None:
    app.storage.user.pop('username', None)


def _get_service(username: str, campaign_id: str | None) -> CampaignService:
    key = (username, campaign_id or '')
    with _lock:
        campaign = _services.get(key)
        if campaign is None:
            campaign = CampaignService(username, campaign_id or '')
            if campaign_id:
                campaign.load()
            _services[key] = campaign
        return campaign


def current_service() -> CampaignService:
    username = current_username()
    if not username:
        return _get_service('', None)
    return _get_service(username, storage.active_campaign_id(username))


def current_campaign_id() -> str | None:
    username = current_username()
    return storage.active_campaign_id(username) if username else None


def list_campaigns() -> list[dict[str, Any]]:
    username = current_username()
    return storage.list_campaigns(username) if username else []


def select_campaign(campaign_id: str) -> CampaignService:
    username = current_username()
    if not username:
        raise RuntimeError('Sign in before selecting a campaign.')
    if not any(item['id'] == campaign_id for item in storage.list_campaigns(username)):
        raise ValueError('Campaign not found in this workspace.')
    storage.set_active_campaign(username, campaign_id)
    return _get_service(username, campaign_id)


def create_campaign(username: str, config: CampaignConfig) -> CampaignService:
    campaign_id = storage.new_campaign_id()
    campaign = CampaignService(username, campaign_id)
    try:
        campaign.create(config)
    except Exception:
        storage.clear(username, campaign_id)
        raise
    storage.set_active_campaign(username, campaign_id)
    with _lock:
        _services[(username, campaign_id)] = campaign
    return campaign


class WorkspaceService:
    """Request-context facade used by the existing page components."""

    def current(self) -> CampaignService:
        return current_service()

    def create_for(self, username: str, config: CampaignConfig) -> CampaignService:
        return create_campaign(username, config)

    def list_campaigns(self) -> list[dict[str, Any]]:
        return list_campaigns()

    def select_campaign(self, campaign_id: str) -> CampaignService:
        return select_campaign(campaign_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(current_service(), name)


service = WorkspaceService()
