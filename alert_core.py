"""Core alert loop for the Discord alert bot.

Supported alert types:
- http: checks URL status code and optional required/forbidden text.
- pickleplus_party: calls the real PicklePlus JSON/XHR API and alerts when
  the configured field says a party-owner slot is open.

Important: api2.amplitude.com/2/httpapi is an analytics event ingestion endpoint.
It records clicks such as role=HOST/MEMBER; it is not a source of availability state.
Use the PicklePlus group-subscription status API instead.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

import alert_config
from discord_notifier import mention, send_discord

MAX_LOG_BYTES = 2_000_000
_MISSING = object()


def now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def make_logger(extra_sink=None):
    os.makedirs(os.path.dirname(alert_config.LOG_FILE), exist_ok=True)

    def _rotate_if_needed() -> None:
        try:
            if (
                os.path.exists(alert_config.LOG_FILE)
                and os.path.getsize(alert_config.LOG_FILE) > MAX_LOG_BYTES
            ):
                backup = alert_config.LOG_FILE + ".1"
                if os.path.exists(backup):
                    os.remove(backup)
                os.replace(alert_config.LOG_FILE, backup)
        except OSError:
            pass

    def log(message: str) -> None:
        line = f"[{now_text()}] {message}"
        if extra_sink is not None:
            try:
                extra_sink(line)
            except Exception:
                pass
        try:
            _rotate_if_needed()
            with open(alert_config.LOG_FILE, "a", encoding="utf-8") as file:
                file.write(line + "\n")
        except OSError:
            pass
        try:
            if sys.stdout is not None:
                print(line, flush=True)
        except Exception:
            pass

    return log


@dataclass
class CheckResult:
    name: str
    ok: bool
    title: str
    detail: str
    target: str
    elapsed_ms: int | None = None


def _format_status_list(statuses: list[int]) -> str:
    return ", ".join(str(status) for status in statuses)


def _safe_json_preview(value: Any, limit: int = 240) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _normalize_compare_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value).strip().lower()


def _is_truthy_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
            "open",
            "opened",
            "available",
            "enable",
            "enabled",
            "possible",
            "host_open",
            "owner_open",
            "party_owner_open",
            "가능",
            "열림",
            "열려있음",
            "모집중",
            "선착순",
            "즉시매칭",
        }
    return bool(value)


def _parse_json_path(path: str) -> list[str | int]:
    """Parse paths like data.items[0].isOpen into ['data', 'items', 0, 'isOpen']."""
    parts: list[str | int] = []
    for chunk in [p for p in path.strip().split(".") if p]:
        start = 0
        match_iter = list(re.finditer(r"\[(\d+)\]", chunk))
        if not match_iter:
            if chunk.isdigit():
                parts.append(int(chunk))
            else:
                parts.append(chunk)
            continue
        for match in match_iter:
            key = chunk[start : match.start()]
            if key:
                parts.append(key)
            parts.append(int(match.group(1)))
            start = match.end()
        tail = chunk[start:]
        if tail:
            parts.append(tail)
    return parts


def _extract_json_path(data: Any, path: str) -> Any:
    current = data
    for part in _parse_json_path(path):
        if isinstance(part, int):
            if isinstance(current, list) and 0 <= part < len(current):
                current = current[part]
            else:
                return _MISSING
        else:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return _MISSING
    return current


def _request_json(alert: dict) -> tuple[requests.Response, Any, int]:
    url = (alert.get("url") or "").strip()
    method = (alert.get("method") or "GET").upper()
    timeout = int(alert.get("timeout_seconds", 15))
    headers = alert.get("headers") or {}
    params = alert.get("params") or {}
    json_body = alert.get("json_body", None)

    started = time.monotonic()
    response = requests.request(
        method,
        url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=timeout,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    response.raise_for_status()
    return response, response.json(), elapsed_ms



def check_http(alert: dict) -> CheckResult:
    """Basic HTTP check kept for compatibility with the original bot template.

    For an HTTP alert, normal means the expected status and optional text checks pass.
    Any mismatch becomes an alert.
    """
    url = (alert.get("url") or "").strip()
    method = (alert.get("method") or "GET").upper()
    timeout = int(alert.get("timeout_seconds", 15))
    headers = alert.get("headers") or {}
    params = alert.get("params") or {}
    json_body = alert.get("json_body", None)
    expected_status = alert.get("expected_status") or [200]
    expected_text = alert.get("expected_text") or ""
    unexpected_text = alert.get("unexpected_text") or ""

    started = time.monotonic()
    response = requests.request(
        method,
        url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=timeout,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if response.status_code not in expected_status:
        return CheckResult(
            name=alert.get("name", "http"),
            ok=False,
            title="Unexpected HTTP status",
            detail=(
                f"HTTP `{response.status_code}` received. "
                f"Expected one of `{_format_status_list(expected_status)}`."
            ),
            target=url,
            elapsed_ms=elapsed_ms,
        )

    text = response.text or ""
    if expected_text and expected_text not in text:
        return CheckResult(
            name=alert.get("name", "http"),
            ok=False,
            title="Expected text not found",
            detail=f"Expected text `{expected_text}` was not found in the response.",
            target=url,
            elapsed_ms=elapsed_ms,
        )

    if unexpected_text and unexpected_text in text:
        return CheckResult(
            name=alert.get("name", "http"),
            ok=False,
            title="Unexpected text found",
            detail=f"Unexpected text `{unexpected_text}` was found in the response.",
            target=url,
            elapsed_ms=elapsed_ms,
        )

    return CheckResult(
        name=alert.get("name", "http"),
        ok=True,
        title="HTTP check passed",
        detail=f"HTTP `{response.status_code}` matched the configured checks.",
        target=url,
        elapsed_ms=elapsed_ms,
    )


def _configured_match(value: Any, candidates: list[Any]) -> bool:
    normalized_value = _normalize_compare_value(value)
    return any(normalized_value == _normalize_compare_value(candidate) for candidate in candidates)


def check_pickleplus_party(alert: dict) -> CheckResult:
    """Check PicklePlus group-subscription status API.

    Semantics are intentionally inverted for alerting:
    - ok=True  means the host slot is still closed/unavailable, so no Discord alert.
    - ok=False means the host slot is open/available, so send Discord alert.
    """
    name = alert.get("name", "pickleplus-party")
    service_name = alert.get("service_name") or name
    url = (alert.get("url") or "").strip()

    if "api2.amplitude.com" in url:
        return CheckResult(
            name=name,
            ok=True,
            title="Analytics endpoint ignored",
            detail="Amplitude is a click analytics endpoint, not a party availability API.",
            target=url,
        )

    response, data, elapsed_ms = _request_json(alert)
    expected_status = alert.get("expected_status") or [200]
    if response.status_code not in expected_status:
        return CheckResult(
            name=name,
            ok=True,
            title="Unexpected HTTP status ignored",
            detail=(
                f"HTTP `{response.status_code}` received. "
                f"Expected one of `{_format_status_list(expected_status)}`."
            ),
            target=url,
            elapsed_ms=elapsed_ms,
        )

    path = alert.get("json_path") or "merchandises[0].host_merchandise.cta_status"
    value = _extract_json_path(data, path)
    if value is _MISSING:
        return CheckResult(
            name=name,
            ok=True,
            title="JSON path missing ignored",
            detail=(
                f"`{path}` was not found. Response preview: "
                f"`{_safe_json_preview(data)}`"
            ),
            target=url,
            elapsed_ms=elapsed_ms,
        )

    open_values = alert.get("open_values") or []
    closed_values = alert.get("closed_values") or []

    if open_values:
        is_open = _configured_match(value, open_values)
    else:
        is_open = _is_truthy_open(value)

    if closed_values and _configured_match(value, closed_values):
        is_open = False

    if is_open:
        return CheckResult(
            name=name,
            ok=False,
            title=f"{service_name} 파티장 열림",
            detail=f"`{path}` 값이 `{value}`입니다. 파티장 신청 가능 상태로 판단했습니다.",
            target=url,
            elapsed_ms=elapsed_ms,
        )

    return CheckResult(
        name=name,
        ok=True,
        title=f"{service_name} 파티장 닫힘",
        detail=f"`{path}` 값이 `{value}`입니다. 아직 파티장 신청 불가 상태입니다.",
        target=url,
        elapsed_ms=elapsed_ms,
    )

def run_check(alert: dict) -> CheckResult:
    alert_type = (alert.get("type") or "http").lower()
    if alert_type == "http":
        return check_http(alert)
    if alert_type == "pickleplus_party":
        return check_pickleplus_party(alert)
    return CheckResult(
        name=alert.get("name", "unknown"),
        ok=False,
        title="Unsupported alert type",
        detail=f"Type `{alert_type}` is not supported.",
        target=alert.get("url", ""),
    )


def format_alert_message(config: dict, result: CheckResult, cycle: int) -> str:
    elapsed = f"\nElapsed: `{result.elapsed_ms}ms`" if result.elapsed_ms is not None else ""
    return (
        f"{mention(config)}**Alert [{result.name}]:** {result.title}\n"
        f"Target: `{result.target}`\n"
        f"Reason: {result.detail}\n"
        f"Cycle: `#{cycle}`{elapsed}\n"
        f"Time: `{now_text()}`"
    )


def format_recovery_message(config: dict, result: CheckResult, cycle: int) -> str:
    elapsed = f"\nElapsed: `{result.elapsed_ms}ms`" if result.elapsed_ms is not None else ""
    return (
        f"{mention(config)}**Recovered [{result.name}]:** Back to normal.\n"
        f"Target: `{result.target}`\n"
        f"Detail: {result.detail}\n"
        f"Cycle: `#{cycle}`{elapsed}\n"
        f"Time: `{now_text()}`"
    )


def _sleep_interruptible(seconds: int, stop_event) -> None:
    end = time.monotonic() + max(0, seconds)
    while time.monotonic() < end:
        if stop_event is not None and stop_event.is_set():
            return
        time.sleep(min(1.0, end - time.monotonic()))


def run_loop(config: dict, log=None, stop_event=None) -> None:
    if log is None:
        log = make_logger()

    config = alert_config.normalize_config(config)
    interval = config["request_interval"]
    max_attempts = config["max_attempts"]
    alerts = [item for item in config["alerts"] if item.get("enabled", True)]

    if not alerts:
        log("No enabled alerts. Nothing to do.")
        return

    log(f"Alert bot started for {len(alerts)} alert(s).")
    log(f"Interval: {interval}s, Max attempts: {max_attempts or 'unlimited'}")

    if config.get("notify_startup", True):
        send_discord(
            config,
            f"**Started:** Alert bot is watching `{len(alerts)}` alert(s).",
            log,
        )

    last_ok: dict[str, bool | None] = {alert["name"]: None for alert in alerts}
    already_alerted: set[str] = set()
    cycle = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            log("Stop requested. Exiting.")
            return

        cycle += 1
        failures: list[CheckResult] = []
        recoveries: list[CheckResult] = []

        for alert in alerts:
            name = alert["name"]
            try:
                result = run_check(alert)
            except Exception as error:
                log(traceback.format_exc())
                # 기본값에서는 네트워크/DNS/API 일시 오류를 Discord 알림으로 보내지 않는다.
                # 이 봇의 목적은 "파티장 열림" 알림이므로, 오류 알림이 필요하면
                # config에서 notify_errors=true로 켜면 된다.
                if not config.get("notify_errors", False):
                    log(f"ERROR [{name}] ignored: {error}")
                    last_ok[name] = True
                    continue
                result = CheckResult(
                    name=name,
                    ok=False,
                    title="Check error",
                    detail=str(error),
                    target=alert.get("url", ""),
                )

            previous = last_ok.get(name)
            last_ok[name] = result.ok

            if result.ok:
                log(f"OK [{name}]: {result.detail}")
                if previous is False and config.get("notify_recovery", True):
                    recoveries.append(result)
            else:
                log(f"ALERT [{name}]: {result.title} - {result.detail}")
                if config.get("notify_once_per_run", False) and name in already_alerted:
                    log(f"ALERT [{name}] already sent in this run; skipping duplicate notification.")
                elif config.get("notify_repeat", True) or previous is not False:
                    failures.append(result)
                    already_alerted.add(name)

        for result in failures:
            send_discord(config, format_alert_message(config, result, cycle), log)
        for result in recoveries:
            send_discord(config, format_recovery_message(config, result, cycle), log)

        heartbeat_every = int(config.get("heartbeat_interval_cycles", 0) or 0)
        if heartbeat_every > 0 and cycle % heartbeat_every == 0:
            failed_count = sum(1 for ok in last_ok.values() if ok is False)
            send_discord(
                config,
                (
                    f"**Heartbeat:** cycle `#{cycle}` complete. "
                    f"Alerts: `{len(alerts)}`, alerting: `{failed_count}`."
                ),
                log,
            )

        if max_attempts > 0 and cycle >= max_attempts:
            log(f"MAX_ATTEMPTS reached ({max_attempts}). Exiting.")
            return

        log(f"Cycle #{cycle} complete. Sleeping {interval}s...")
        _sleep_interruptible(interval, stop_event)
