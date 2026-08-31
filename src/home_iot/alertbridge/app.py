"""Turn Alertmanager webhook payloads into readable ntfy notifications.

Alertmanager has no native ntfy receiver and ntfy does not parse the webhook
JSON, so this ~small service sits between them: ``POST /alert`` (Alertmanager
``webhook_configs``) -> one ntfy message per alert with a title, priority and
tags derived from ``severity``.

:func:`format_alert` is pure and unit-tested.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Tuple

import requests
from aiohttp import web
from loguru import logger

from ..common import env_str, read_secret

# severity -> (ntfy priority, tags, emoji prefix)
_SEVERITY = {
    "critical": ("5", "rotating_light", "🚨"),
    "warning": ("4", "warning", "⚠️"),
    "info": ("2", "information_source", "ℹ️"),
}
_RESOLVED = ("3", "white_check_mark", "✅")


def _cfg() -> Dict[str, str]:
    return {
        "url": env_str("NTFY_URL", "https://ntfy.sh").rstrip("/"),
        "topic": read_secret(env_str("NTFY_TOPIC")),
        "token": read_secret(env_str("NTFY_TOKEN")),
    }


def format_alert(alert: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """Return (title, body, priority, tags) for one Alertmanager alert."""
    labels = alert.get("labels") or {}
    ann = alert.get("annotations") or {}
    status = alert.get("status", "firing")
    severity = str(labels.get("severity", "info")).lower()

    if status == "resolved":
        prio, tags, emoji = _RESOLVED
        verb = "RESOLVED"
    else:
        prio, tags, emoji = _SEVERITY.get(severity, _SEVERITY["info"])
        verb = severity.upper()

    name = labels.get("alertname", "alert")
    title = f"{emoji} {verb}: {ann.get('summary') or name}"
    lines = [f"{emoji} {verb} — {name}"]
    if ann.get("description"):
        lines.append(ann["description"])
    ctx = [
        f"{k}={v}"
        for k, v in labels.items()
        if k not in ("alertname", "severity", "__name__")
    ]
    if ctx:
        lines.append("`" + " ".join(sorted(ctx)) + "`")
    return title[:250], "\n".join(lines) or name, prio, tags


def _ascii(text: str) -> str:
    """HTTP headers are latin-1 only — drop anything else (e.g. emoji)."""
    return text.encode("ascii", "ignore").decode("ascii").strip() or "alert"


def _publish(cfg: Dict[str, str], title: str, body: str, prio: str, tags: str) -> None:
    headers: Dict[str, str] = {
        "Title": _ascii(title),
        "Priority": prio,
        "Tags": tags,
        "Markdown": "yes",
    }
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    resp = requests.post(
        f"{cfg['url']}/{cfg['topic']}",
        data=body.encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()


async def handle_alert(request: web.Request) -> web.Response:
    cfg = _cfg()
    if not cfg["topic"]:
        return web.Response(status=503, text="NTFY_TOPIC not configured")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.Response(status=400, text="bad json")

    alerts = payload.get("alerts") or []
    sent = 0
    for alert in alerts:
        title, body, prio, tags = format_alert(alert)
        try:
            _publish(cfg, title, body, prio, tags)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("ntfy publish failed: {}", exc)
    logger.info("forwarded {}/{} alert(s) to ntfy", sent, len(alerts))
    return web.json_response({"forwarded": sent, "received": len(alerts)})


async def handle_test(request: web.Request) -> web.Response:
    cfg = _cfg()
    if not cfg["topic"]:
        return web.Response(status=503, text="NTFY_TOPIC not configured")
    _publish(
        cfg,
        "✅ Alert bridge test",
        f"fritz-monitoring alertbridge reachable at {time.strftime('%H:%M:%S')}",
        "3",
        "white_check_mark",
    )
    return web.Response(text="sent")


async def handle_healthz(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


def build_app() -> web.Application:
    app = web.Application()
    app.add_routes(
        [
            web.post("/alert", handle_alert),
            web.get("/test", handle_test),
            web.get("/healthz", handle_healthz),
        ]
    )
    return app


def main() -> None:
    cfg = _cfg()
    if not cfg["topic"]:
        logger.warning("NTFY_TOPIC not set — /alert will 503 until it is.")
    else:
        logger.info("alertbridge -> {}/{}", cfg["url"], cfg["topic"])
    web.run_app(build_app(), host="0.0.0.0", port=9127, print=None)


if __name__ == "__main__":
    main()
