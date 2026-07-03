"""Discord notification helpers."""

from __future__ import annotations

import requests


def mention(config: dict) -> str:
    user_id = (config.get("discord_user_id") or "").strip()
    return f"<@{user_id}> " if user_id else ""


def send_discord(config: dict, message: str, log) -> None:
    """Send a Discord webhook message using the same simple content format as OIC."""
    url = (config.get("discord_webhook_url") or "").strip()
    if not url:
        return
    try:
        response = requests.post(url, json={"content": message}, timeout=15)
        response.raise_for_status()
    except Exception as error:
        log(f"Discord notification failed: {error}")
