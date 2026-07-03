"""Headless CLI runner for the PicklePlus Discord alert bot.

Secrets handling for GitHub Actions:
- DISCORD_WEBHOOK_URL is the only required secret.
- DISCORD_USER_ID is optional.
- PICKLEPLUS_SERVICES is an optional GitHub Variable, not a secret.

Usage:
    python run_alert_bot.py [--config PATH] [--once]
"""

from __future__ import annotations

import argparse
import os
import sys

import alert_config
import alert_core


def _parse_services_env(raw: str) -> list[dict]:
    """Parse compact service config from an environment variable.

    Supported formats, separated by comma or newline:
    - millie
    - millie=밀리의 서재 전자책 정기구독 파티장
    - millie|밀리의 서재 전자책 정기구독 파티장
    - https://prd-main-api.pickle.plus/services/millie/group-subscription/status|밀리의 서재
    """
    services: list[dict] = []
    if not raw:
        return services

    for item in raw.replace("\n", ",").split(","):
        item = item.strip()
        if not item:
            continue

        if "|" in item:
            key, label = item.split("|", 1)
        elif "=" in item:
            key, label = item.split("=", 1)
        else:
            key, label = item, ""

        key = key.strip()
        label = label.strip()
        if not key:
            continue

        if key.startswith("http://") or key.startswith("https://"):
            service = {"status_url": key}
        else:
            service = {"slug": key}
        if label:
            service["service_name"] = label
        services.append(service)

    return services


def load_or_create(config_path: str, log) -> dict:
    if os.path.exists(config_path):
        return alert_config.load_config(config_path)

    if config_path == alert_config.CONFIG_PATH and os.path.exists(alert_config.TEMPLATE_CONFIG_PATH):
        log(f"No config.json found. Loading {alert_config.TEMPLATE_CONFIG_FILENAME}.")
        return alert_config.load_config(config_path)

    log(
        f"No config found at {config_path}. A template was created; "
        "fill it in and run again."
    )
    alert_config.save_config(alert_config.default_config(), config_path)
    return alert_config.load_config(config_path)


def apply_env_overrides(config: dict, log) -> dict:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook is not None and webhook.strip():
        config["discord_webhook_url"] = webhook.strip()
        log("Discord webhook URL loaded from environment.")

    user_id = os.environ.get("DISCORD_USER_ID")
    if user_id is not None and user_id.strip():
        config["discord_user_id"] = user_id.strip()
        log("Discord user ID loaded from environment.")

    services_raw = os.environ.get("PICKLEPLUS_SERVICES")
    if services_raw is not None and services_raw.strip():
        services = _parse_services_env(services_raw)
        if services:
            config["services"] = services
            config["alerts"] = []
            log(f"PicklePlus services loaded from environment: {len(services)} service(s).")

    return alert_config.normalize_config(config)


def main() -> None:
    parser = argparse.ArgumentParser(description="PicklePlus Discord alert bot")
    parser.add_argument(
        "--config",
        default=alert_config.CONFIG_PATH,
        help="Path to config.json (default: next to this script; falls back to config.example.json)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check cycle and exit.",
    )
    args = parser.parse_args()

    log = alert_core.make_logger()
    config = load_or_create(args.config, log)
    config = apply_env_overrides(config, log)

    if args.once:
        config["max_attempts"] = 1

    try:
        alert_core.run_loop(config, log=log)
    except KeyboardInterrupt:
        log("Interrupted by user. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
