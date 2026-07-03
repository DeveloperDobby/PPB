from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

CONFIG_FILENAME = "config.json"
TEMPLATE_CONFIG_FILENAME = "config.example.json"

PICKLEPLUS_API_BASE = "https://prd-main-api.pickle.plus"
DEFAULT_JSON_PATH = "merchandises[0].host_merchandise.cta_status"


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, CONFIG_FILENAME)
TEMPLATE_CONFIG_PATH = os.path.join(BASE_DIR, TEMPLATE_CONFIG_FILENAME)
LOG_FILE = os.path.join(BASE_DIR, "logs", "output.log")


DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "ko-KR,ko;q=0.9",
    "cloudfront-viewer-country": "KR",
    "user-agent": "Mozilla/5.0",
}

DEFAULT_OPEN_VALUES = [
    "AVAILABLE",
    "PARTY_HOST_AVAILABLE",
    "HOST_AVAILABLE",
    "OPEN",
]

DEFAULT_CLOSED_VALUES = [
    "PARTY_HOST_UNAVAILABLE",
    "UNAVAILABLE",
    "CLOSED",
]


def _slug_to_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", value.strip()).strip("-")
    return value.lower() or "pickleplus-service"


def _status_url_from_slug(slug: str) -> str:
    slug = slug.strip("/")
    return f"{PICKLEPLUS_API_BASE}/services/{slug}/group-subscription/status"


def _default_services() -> list[dict[str, Any]]:
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


def default_config() -> dict[str, Any]:
    return {
        "request_interval": 300,
        "max_attempts": 72,
        "bot_name": "PicklePlus 파티장 알림봇",
        "notify_startup": False,
        "notify_repeat": False,
        "notify_recovery": False,
        "notify_once_per_run": True,
        "notify_errors": False,
        "heartbeat_interval_cycles": 0,
        "services": _default_services(),
        "alerts": [],
    }


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _as_status_list(value: Any, default: list[int]) -> list[int]:
    if value is None:
        return default[:]
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, list):
        items = value
    else:
        return default[:]

    result: list[int] = []
    for item in items:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result or default[:]


def _normalize_service(service: Any, index: int) -> dict[str, Any] | None:
    if isinstance(service, str):
        service = {"slug": service}
    if not isinstance(service, dict):
        return None

    slug = str(service.get("slug") or "").strip().strip("/")
    status_url = str(
        service.get("status_url") or service.get("url") or ""
    ).strip()

    if not status_url and slug:
        status_url = _status_url_from_slug(slug)

    if not status_url:
        return None

    service_name = str(service.get("service_name") or service.get("label") or slug or status_url).strip()
    merchandise_index = _as_int(service.get("merchandise_index", 0), default=0)
    json_path = str(
        service.get("json_path")
        or f"merchandises[{merchandise_index}].host_merchandise.cta_status"
    ).strip()
    name = str(service.get("name") or f"pickleplus-{_slug_to_name(slug or service_name)}-host").strip()

    return {
        "name": name,
        "enabled": _as_bool(service.get("enabled"), default=True),
        "type": "pickleplus_party",
        "service_name": service_name,
        "url": status_url,
        "method": str(service.get("method") or "GET").upper(),
        "timeout_seconds": _as_int(service.get("timeout_seconds", 15), default=15),
        "expected_status": _as_status_list(service.get("expected_status"), [200]),
        "headers": {**DEFAULT_HEADERS, **(service.get("headers") or {})},
        "json_path": json_path,
        "open_values": service.get("open_values") or DEFAULT_OPEN_VALUES[:],
        "closed_values": service.get("closed_values") or DEFAULT_CLOSED_VALUES[:],
    }


def _normalize_alert(alert: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(alert, dict):
        return None

    alert_type = str(alert.get("type") or "pickleplus_party").lower()
    item = dict(alert)
    item["type"] = alert_type
    item["enabled"] = _as_bool(item.get("enabled"), default=True)
    item["name"] = str(item.get("name") or f"alert-{index + 1}").strip()
    item["method"] = str(item.get("method") or "GET").upper()
    item["timeout_seconds"] = _as_int(item.get("timeout_seconds", 15), default=15)
    item["expected_status"] = _as_status_list(item.get("expected_status"), [200])

    if alert_type == "pickleplus_party":
        item.setdefault("headers", DEFAULT_HEADERS.copy())
        item["headers"] = {**DEFAULT_HEADERS, **(item.get("headers") or {})}
        item.setdefault("json_path", DEFAULT_JSON_PATH)
        item.setdefault("open_values", DEFAULT_OPEN_VALUES[:])
        item.setdefault("closed_values", DEFAULT_CLOSED_VALUES[:])

    return item


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    base = default_config()
    merged = {**base, **{k: v for k, v in config.items() if k not in {"services", "alerts"}}}

    merged["request_interval"] = _as_int(merged.get("request_interval"), default=300)
    merged["max_attempts"] = _as_int(merged.get("max_attempts"), default=72)

    for key, default in (
        ("mention_each_message", True),
        ("notify_startup", False),
        ("notify_repeat", False),
        ("notify_recovery", False),
        ("notify_once_per_run", True),
        ("notify_errors", False),
    ):
        merged[key] = _as_bool(merged.get(key), default=default)

    merged["heartbeat_interval_cycles"] = _as_int(
        merged.get("heartbeat_interval_cycles"), default=0
    )

    raw_services = config.get("services")
    if raw_services is None:
        raw_services = base["services"]
    if not isinstance(raw_services, list):
        raw_services = []

    services = []
    generated_alerts = []
    for index, service in enumerate(raw_services):
        normalized_service = _normalize_service(service, index)
        if normalized_service is not None:
            services.append(service)
            generated_alerts.append(normalized_service)

    raw_alerts = config.get("alerts") or []
    normalized_alerts = []
    if isinstance(raw_alerts, list) and raw_alerts:
        for index, alert in enumerate(raw_alerts):
            normalized_alert = _normalize_alert(alert, index)
            if normalized_alert is not None:
                normalized_alerts.append(normalized_alert)
    else:
        normalized_alerts = generated_alerts

    merged["services"] = services
    merged["alerts"] = normalized_alerts
    return merged


def load_config(path: str = CONFIG_PATH) -> dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"config 파일이 없습니다: {path}\n"
            f"{TEMPLATE_CONFIG_FILENAME}을 config.json으로 복사한 뒤 실행하세요."
        )

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 형식이 올바르지 않습니다: {path}\n{error}") from error

    if not isinstance(data, dict):
        raise ValueError("config의 최상위 구조는 JSON object여야 합니다.")

    return normalize_config(data)


def save_config(config: dict[str, Any], path: str = CONFIG_PATH) -> None:
    normalized = normalize_config(config)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)
