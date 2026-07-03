from __future__ import annotations

import json
import os
import sys
from typing import Any

CONFIG_FILENAME = "config.json"


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, CONFIG_FILENAME)
LOG_FILE = os.path.join(BASE_DIR, "logs", "output.log")


def default_message(name: str = "heartbeat") -> dict[str, Any]:
    return {
        "name": name,
        "enabled": True,
        "title": "정기 알림",
        "body": "봇이 정상 작동 중입니다.",
        "footer": "GitHub Actions periodic notifier",
    }


def default_config() -> dict[str, Any]:
    return {
        "request_interval": 1800,
        "max_attempts": 0,
        "bot_name": "알림봇",
        "discord_webhook_url": "",
        "discord_user_id": "",
        "mention_each_message": False,
        "messages": [default_message()],
    }


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    base = default_config()
    merged = {**base, **{k: v for k, v in config.items() if k != "messages"}}

    for key in ("request_interval", "max_attempts"):
        try:
            merged[key] = int(merged.get(key, 0) or 0)
        except (TypeError, ValueError):
            merged[key] = 0

    merged["mention_each_message"] = _as_bool(
        merged.get("mention_each_message"), default=False
    )

    messages = config.get("messages") or []
    if not messages:
        messages = [default_message()]

    normalized_messages = []
    for index, message in enumerate(messages):
        template = default_message(f"message-{index + 1}")
        item = {**template, **(message or {})}
        item["enabled"] = _as_bool(item.get("enabled"), default=True)
        normalized_messages.append(item)

    merged["messages"] = normalized_messages
    return merged


def load_config(path: str = CONFIG_PATH) -> dict[str, Any]:
    """
    config.json을 반드시 읽는다.

    config.json이 없으면 기본값으로 실행하지 않고 즉시 오류를 발생시킨다.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"config.json 파일이 없습니다: {path}\n"
            "config.example.json을 config.json으로 복사한 뒤 값을 채워주세요."
        )

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"config.json JSON 형식이 올바르지 않습니다: {path}\n{error}"
        ) from error

    if not isinstance(data, dict):
        raise ValueError("config.json의 최상위 구조는 JSON object여야 합니다.")

    return normalize_config(data)


def save_config(config: dict[str, Any], path: str = CONFIG_PATH) -> None:
    normalized = normalize_config(config)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)
