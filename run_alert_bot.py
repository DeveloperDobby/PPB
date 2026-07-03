"""Headless CLI runner for the PicklePlus Discord alert bot.

Configuration policy for GitHub Actions:
- CONFIG_JSON GitHub Secret is required.
- CONFIG_JSON must contain watcher settings only. Discord values are ignored there.
- The bot does not load config.json automatically.
- GitHub Variables are not used.
- DISCORD_WEBHOOK_URL is required as a separate GitHub Secret.
- DISCORD_USER_ID is optional as a separate GitHub Secret.

Usage:
    CONFIG_JSON='{"services":[...]}' DISCORD_WEBHOOK_URL='...' python run_alert_bot.py [--once]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import alert_config
import alert_core


DISCORD_CONFIG_KEYS = {
    "discord_webhook_url",
    "discord_user_id",
    "mention_each_message",
}


def _remove_discord_keys(data: dict, log) -> dict:
    cleaned = dict(data)
    removed = sorted(key for key in DISCORD_CONFIG_KEYS if key in cleaned)
    for key in removed:
        cleaned.pop(key, None)
    if removed:
        log(
            "Discord-related key(s) in CONFIG_JSON were ignored: "
            + ", ".join(removed)
        )
    return cleaned


def load_required_config_from_secret(log) -> dict:
    """Load watcher configuration from CONFIG_JSON. Discord keys are ignored."""
    raw = os.environ.get("CONFIG_JSON", "")
    if not raw.strip():
        log("CONFIG_JSON secret is missing or empty. Bot will not start.")
        raise RuntimeError("CONFIG_JSON secret is required")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"CONFIG_JSON is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError("CONFIG_JSON top-level value must be a JSON object.")

    return alert_config.normalize_config(_remove_discord_keys(data, log))


def apply_discord_secrets(config: dict, log) -> dict:
    """Load Discord settings only from separate environment variables."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        log("DISCORD_WEBHOOK_URL secret is missing or empty. Bot will not start.")
        raise RuntimeError("DISCORD_WEBHOOK_URL secret is required")

    config["discord_webhook_url"] = webhook
    log("Discord webhook URL loaded from DISCORD_WEBHOOK_URL secret.")

    user_id = os.environ.get("DISCORD_USER_ID", "").strip()
    if user_id:
        config["discord_user_id"] = user_id
        log("Discord user ID loaded from DISCORD_USER_ID secret.")

    # CONFIG_JSON cannot control Discord mention behavior.
    # Mention is sent only when DISCORD_USER_ID is set.
    config["mention_each_message"] = bool(user_id)

    return alert_config.normalize_config(config)


def main() -> None:
    parser = argparse.ArgumentParser(description="PicklePlus Discord alert bot")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check cycle and exit.",
    )
    args = parser.parse_args()

    log = alert_core.make_logger()

    try:
        config = load_required_config_from_secret(log)
        config = apply_discord_secrets(config, log)
    except Exception as error:
        log(f"Bot did not start: {error}")
        sys.exit(1)

    if args.once:
        config["max_attempts"] = 1

    try:
        alert_core.run_loop(config, log=log)
    except KeyboardInterrupt:
        log("Interrupted by user. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
