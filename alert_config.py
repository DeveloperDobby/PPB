"""Configuration handling for the PicklePlus Discord alert bot.

The bot intentionally keeps sensitive values out of config files.
- Put DISCORD_WEBHOOK_URL in GitHub Secrets.
- Keep public PicklePlus service slugs/URLs in config.example.json or GitHub Variables.
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from typing import Any

CONFIG_FILENAME = "config.json"
TEMPLATE_CONFIG_FILENAME = "config.example.json"

PICKLEPLUS_BASE_URL = "https://prd-main-api.pickle.plus"
PICKLEPLUS_DEFAULT_JSON_PATH = "merchandises[0].host_merchandise.cta_status"
PICKLEPLUS_DEFAULT_OPEN_VALUES = [
    "AVAILABLE",
    "PARTY_HOST_AVAILABLE",
    "HOST_AVAILABLE",
    "OPEN",
]
PICKLEPLUS_DEFAULT_CLOSED_VALUES = [
    "PARTY_HOST_UNAVAILABLE",
    "UNAVAILABLE",
    "CLOSED",
]
PICKLEPLUS_DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "ko-KR,ko;q=0.9",
    "cloudfront-viewer-country": "KR",
    "user-agent": "Mozilla/5.0",
}


def get_base_dir() -> str:
    """Folder of the executable when frozen, otherwise this source folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, CONFIG_FILENAME)
TEMPLATE_CONFIG_PATH = os.path.join(BASE_DIR, TEMPLATE_CONFIG_FILENAME)
LOG_FILE = os.path.join(BASE_DIR, "logs", "output.log")


def default_alert(name: str = "homepage") -> dict:
    return {
        "name": name,
        "enabled": True,
        "type": "http",
        "url": "https://example.com",
        "method": "GET",
        "timeout_seconds": 15,
        "expected_status": [200],
        "expected_text": "",
        "unexpected_text": "",
    }


def default_services() -> list[dict]:
    return [
        {
            "slug": "disneyplus-sharing",
            "service_name": "구 디즈니+ 프리미엄 파티장",
        },
        {
            "slug": "millie",
            "service_name": "밀리의 서재 전자책 정기구독 파티장",
        },
    ]


def default_config() -> dict:
    return {
        "request_interval": 300,
        "max_attempts": 72,
        "discord_webhook_url": "",
        "discord_user_id": "",
        "notify_startup": False,
        "notify_repeat": False,
        "notify_recovery": False,
        "notify_once_per_run": True,
        "heartbeat_interval_cycles": 0,
        "services": default_services(),
        "alerts": [],
    }


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slug_to_status_url(slug: str) -> str:
    cleaned = slug.strip().strip("/")
    return f"{PICKLEPLUS_BASE_URL}/services/{cleaned}/group-subscription/status"


def _service_to_alert(service: Any, index: int) -> dict:
    """Convert a compact service item into a full alert item.

    Supported compact forms:
    - "millie"
    - {"slug": "millie", "service_name": "밀리의 서재 파티장"}
    - {"status_url": "https://.../status", "service_name": "..."}
    """
    if isinstance(service, str):
        slug = service.strip()
        service_name = slug
        status_url = _slug_to_status_url(slug)
        name = f"pickleplus-{slug}-host"
        enabled = True
        merchandise_index = 0
    elif isinstance(service, dict):
        slug = str(service.get("slug") or "").strip()
        status_url = str(service.get("status_url") or service.get("url") or "").strip()
        if not status_url:
            if not slug:
                slug = f"service-{index + 1}"
            status_url = _slug_to_status_url(slug)
        service_name = str(service.get("service_name") or service.get("name") or slug or status_url).strip()
        safe_slug = slug or service_name or f"service-{index + 1}"
        name = str(service.get("alert_name") or f"pickleplus-{safe_slug}-host").strip()
        enabled = _as_bool(service.get("enabled"), True)
        merchandise_index = _as_int(service.get("merchandise_index"), 0)
    else:
        slug = f"service-{index + 1}"
        service_name = slug
        status_url = _slug_to_status_url(slug)
        name = f"pickleplus-{slug}-host"
        enabled = True
        merchandise_index = 0

    json_path = PICKLEPLUS_DEFAULT_JSON_PATH
    if merchandise_index != 0:
        json_path = f"merchandises[{merchandise_index}].host_merchandise.cta_status"
    if isinstance(service, dict) and service.get("json_path"):
        json_path = str(service["json_path"])

    headers = deepcopy(PICKLEPLUS_DEFAULT_HEADERS)
    if isinstance(service, dict) and isinstance(service.get("headers"), dict):
        headers.update(service["headers"])

    return {
        "name": name,
        "enabled": enabled,
        "type": "pickleplus_party",
        "service_name": service_name,
        "url": status_url,
        "method": "GET",
        "timeout_seconds": 15,
        "expected_status": [200],
        "headers": headers,
        "params": {},
        "json_body": None,
        "json_path": json_path,
        "open_values": list(PICKLEPLUS_DEFAULT_OPEN_VALUES),
        "closed_values": list(PICKLEPLUS_DEFAULT_CLOSED_VALUES),
    }


def _normalize_alert(alert: dict, index: int) -> dict:
    template = default_alert(f"alert-{index + 1}")
    item = {**deepcopy(template), **(alert or {})}
    item["enabled"] = _as_bool(item.get("enabled"), True)
    item["timeout_seconds"] = max(1, _as_int(item.get("timeout_seconds"), 15))
    expected_status = item.get("expected_status", [200])
    if isinstance(expected_status, int):
        expected_status = [expected_status]
    elif not isinstance(expected_status, list):
        expected_status = [200]
    item["expected_status"] = [_as_int(status, 200) for status in expected_status]
    return item


def normalize_config(config: dict) -> dict:
    """Fill missing keys using defaults and coerce important types."""
    source = config or {}
    base = default_config()
    merged = {**base, **{k: v for k, v in source.items() if k not in {"alerts", "services"}}}

    merged["request_interval"] = max(1, _as_int(merged.get("request_interval"), 300))
    merged["max_attempts"] = max(0, _as_int(merged.get("max_attempts"), 72))
    merged["heartbeat_interval_cycles"] = max(
        0, _as_int(merged.get("heartbeat_interval_cycles"), 0)
    )
    for key in ("notify_startup", "notify_repeat", "notify_recovery", "notify_once_per_run"):
        merged[key] = _as_bool(merged.get(key), bool(base[key]))

    services = source.get("services")
    if services is None:
        services = base.get("services", [])
    if isinstance(services, str):
        services = [part.strip() for part in services.split(",") if part.strip()]
    elif not isinstance(services, list):
        services = []
    merged["services"] = services

    alerts: list[dict] = []
    for index, service in enumerate(services):
        alerts.append(_service_to_alert(service, index))

    explicit_alerts = source.get("alerts") or []
    if isinstance(explicit_alerts, dict):
        explicit_alerts = [explicit_alerts]
    if isinstance(explicit_alerts, list):
        offset = len(alerts)
        for index, alert in enumerate(explicit_alerts):
            alerts.append(_normalize_alert(alert or {}, offset + index))

    if not alerts:
        alerts = [_normalize_alert(default_alert(), 0)]

    merged["alerts"] = alerts
    return merged


def load_config(path: str = CONFIG_PATH) -> dict:
    load_path = path
    if not os.path.exists(load_path) and path == CONFIG_PATH and os.path.exists(TEMPLATE_CONFIG_PATH):
        load_path = TEMPLATE_CONFIG_PATH
    if not os.path.exists(load_path):
        return normalize_config(default_config())
    with open(load_path, "r", encoding="utf-8") as file:
        return normalize_config(json.load(file))


def save_config(config: dict, path: str = CONFIG_PATH) -> None:
    normalized = normalize_config(config)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)
