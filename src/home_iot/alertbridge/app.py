"""Alertmanager -> ntfy bridge + dead-man's-switch.

* ``POST /alert``   — Alertmanager webhook -> one ntfy push per alert.
* ``POST /watchdog``— receives the always-firing ``Watchdog`` alert; records
  the time. A background task fires a **direct** ntfy warning (bypassing
  Alertmanager) if no Watchdog arrives for ``DEADMAN_STALE_SECONDS`` — i.e. the
  alerting pipeline itself broke. If ``DEADMAN_URL`` is set it is also pinged on
  every Watchdog (healthchecks.io-style external observer = a true DMS).
* ``GET /metrics``  — alertbridge_* counters for Prometheus.

:func:`format_alert` is pure and unit-tested.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Tuple

import requests
from aiohttp import web
from loguru import logger
from prometheus_client import Counter, Gauge, generate_latest

from ..common import env_float, env_str, read_secret

_SEVERITY = {
    "critical": ("5", "rotating_light", "🚨"),
    "warning": ("4", "warning", "⚠️"),
    "info": ("2", "information_source", "ℹ️"),
}
_RESOLVED = ("3", "white_check_mark", "✅")

_forwarded = Counter("alertbridge_alerts_forwarded_total", "Alerts pushed to ntfy")
_failed = Counter("alertbridge_publish_failures_total", "ntfy publish failures")
_watchdog_seen = Gauge(
    "alertbridge_watchdog_last_seen_timestamp_seconds",
    "Unix time the last Watchdog alert was received from Alertmanager",
)
_deadman_fires = Counter(
    "alertbridge_deadman_fires_total", "Times the dead-man's-switch tripped"
)

_last_watchdog = time.time()  # module state; the Gauge mirrors it


def _cfg() -> Dict[str, str]:
    return {
        "url": env_str("NTFY_URL", "https://ntfy.sh").rstrip("/"),
        "topic": read_secret(env_str("NTFY_TOPIC")),
        "token": read_secret(env_str("NTFY_TOKEN")),
        "deadman_url": env_str("DEADMAN_URL"),
        "telegram_token": read_secret(env_str("TELEGRAM_BOT_TOKEN")),
        "telegram_chat_id": env_str("TELEGRAM_CHAT_ID"),
        "pushover_user": read_secret(env_str("PUSHOVER_USER_KEY")),
        "pushover_token": read_secret(env_str("PUSHOVER_API_TOKEN")),
        "discord_webhook": read_secret(env_str("DISCORD_WEBHOOK_URL")),
        "whatsapp_phone": env_str("WHATSAPP_PHONE"),
        "whatsapp_api_key": read_secret(env_str("WHATSAPP_API_KEY")),
        "smtp_host": env_str("SMTP_HOST"),
        "smtp_port": env_str("SMTP_PORT", "587"),
        "smtp_user": env_str("SMTP_USER"),
        "smtp_password": read_secret(env_str("SMTP_PASSWORD")),
        "smtp_to": env_str("EMAIL_TO"),
        "smtp_from": env_str("SMTP_FROM"),
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
    return text.encode("ascii", "ignore").decode("ascii").strip() or "alert"


def _publish(cfg: Dict[str, str], title: str, body: str, prio: str, tags: str) -> None:
    sent_any = False
    errors: list[str] = []

    # 1. ntfy.sh
    if cfg.get("topic"):
        headers: Dict[str, str] = {
            "Title": _ascii(title),
            "Priority": prio,
            "Tags": tags,
            "Markdown": "yes",
        }
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        try:
            resp = requests.post(
                f"{cfg['url']}/{cfg['topic']}",
                data=body.encode("utf-8"),
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            sent_any = True
        except Exception as exc:
            errors.append(f"ntfy: {exc}")

    # 2. Telegram
    if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
        try:
            tg_text = f"*{title}*\n\n{body}"
            resp = requests.post(
                f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage",
                json={
                    "chat_id": cfg["telegram_chat_id"],
                    "text": tg_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            sent_any = True
        except Exception as exc:
            errors.append(f"telegram: {exc}")

    # 3. Pushover
    if cfg.get("pushover_user") and cfg.get("pushover_token"):
        try:
            po_prio = int(prio) - 3  # ntfy 1-5 -> pushover -2 to 2
            resp = requests.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": cfg["pushover_token"],
                    "user": cfg["pushover_user"],
                    "title": title,
                    "message": body,
                    "priority": po_prio,
                },
                timeout=10,
            )
            resp.raise_for_status()
            sent_any = True
        except Exception as exc:
            errors.append(f"pushover: {exc}")

    # 4. Discord Webhook
    if cfg.get("discord_webhook"):
        try:
            color = 15158332 if "CRITICAL" in title else (15105570 if "WARNING" in title else 3447003)
            resp = requests.post(
                cfg["discord_webhook"],
                json={
                    "embeds": [
                        {
                            "title": title,
                            "description": body,
                            "color": color,
                        }
                    ]
                },
                timeout=10,
            )
            resp.raise_for_status()
            sent_any = True
        except Exception as exc:
            errors.append(f"discord: {exc}")

    # 5. WhatsApp (CallMeBot)
    if cfg.get("whatsapp_phone") and cfg.get("whatsapp_api_key"):
        try:
            wa_text = f"*{title}*\n\n{body}"
            resp = requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={
                    "phone": cfg["whatsapp_phone"],
                    "text": wa_text,
                    "apikey": cfg["whatsapp_api_key"],
                },
                timeout=15,
            )
            resp.raise_for_status()
            sent_any = True
        except Exception as exc:
            errors.append(f"whatsapp: {exc}")

    # 6. Email (SMTP)
    if cfg.get("smtp_host") and cfg.get("smtp_to"):
        try:
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["Subject"] = title
            msg["From"] = cfg.get("smtp_from") or cfg.get("smtp_user") or "alerts@fritz.monitoring"
            msg["To"] = cfg["smtp_to"]
            msg.set_content(body)

            port = int(cfg.get("smtp_port") or 587)
            with smtplib.SMTP(cfg["smtp_host"], port, timeout=15) as s:
                s.starttls()
                if cfg.get("smtp_user") and cfg.get("smtp_password"):
                    s.login(cfg["smtp_user"], cfg["smtp_password"])
                s.send_message(msg)
            sent_any = True
        except Exception as exc:
            errors.append(f"smtp_email: {exc}")

    if not sent_any and errors:
        raise RuntimeError("; ".join(errors))


async def handle_alert(request: web.Request) -> web.Response:
    cfg = _cfg()
    has_target = bool(
        cfg.get("topic")
        or (cfg.get("telegram_token") and cfg.get("telegram_chat_id"))
        or (cfg.get("pushover_user") and cfg.get("pushover_token"))
        or cfg.get("discord_webhook")
        or (cfg.get("whatsapp_phone") and cfg.get("whatsapp_api_key"))
        or (cfg.get("smtp_host") and cfg.get("smtp_to"))
    )
    if not has_target:
        return web.Response(status=503, text="No alert notification channel configured")
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
            _forwarded.inc()
        except Exception as exc:  # noqa: BLE001
            _failed.inc()
            logger.warning("ntfy publish failed: {}", exc)
    logger.info("forwarded {}/{} alert(s) to ntfy", sent, len(alerts))
    return web.json_response({"forwarded": sent, "received": len(alerts)})


async def handle_watchdog(request: web.Request) -> web.Response:
    global _last_watchdog
    _last_watchdog = time.time()
    _watchdog_seen.set(_last_watchdog)
    cfg = _cfg()
    if cfg["deadman_url"]:
        try:
            requests.get(cfg["deadman_url"], timeout=8)
        except Exception as exc:  # noqa: BLE001
            logger.warning("deadman ping failed: {}", exc)
    return web.Response(text="ok")


async def handle_test(_request: web.Request) -> web.Response:
    cfg = _cfg()
    has_target = bool(
        cfg.get("topic")
        or (cfg.get("telegram_token") and cfg.get("telegram_chat_id"))
        or (cfg.get("pushover_user") and cfg.get("pushover_token"))
        or cfg.get("discord_webhook")
    )
    if not has_target:
        return web.Response(status=503, text="No alert notification channel configured")
    _publish(
        cfg,
        "✅ Alert bridge test",
        f"alertbridge reachable at {time.strftime('%H:%M:%S')}",
        "3",
        "white_check_mark",
    )
    return web.Response(text="sent")


async def handle_metrics(_request: web.Request) -> web.Response:
    # note: aiohttp rejects a charset in content_type, so keep it bare
    return web.Response(body=generate_latest(), content_type="text/plain")


async def handle_healthz(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def _deadman_loop(stale_after: float) -> None:
    """If no Watchdog for `stale_after` s, ntfy a warning directly (once)."""
    alarmed = False
    _watchdog_seen.set(_last_watchdog)  # cold start grace
    while True:
        await asyncio.sleep(60)
        stale = time.time() - _last_watchdog > stale_after
        if stale and not alarmed:
            alarmed = True
            _deadman_fires.inc()
            cfg = _cfg()
            logger.error("DEAD-MAN'S-SWITCH: no Watchdog for {}s", stale_after)
            if cfg["topic"]:
                try:
                    _publish(
                        cfg,
                        "🚨 ALERTING PIPELINE DOWN",
                        "No Watchdog from Alertmanager for "
                        f"{int(time.time() - _last_watchdog)}s. Prometheus or Alertmanager "
                        "may be down — other alerts are NOT being delivered.",
                        "5",
                        "rotating_light",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("deadman ntfy failed too: {}", exc)
        elif not stale:
            alarmed = False


def build_app() -> web.Application:
    app = web.Application()
    app.add_routes(
        [
            web.post("/alert", handle_alert),
            web.post("/watchdog", handle_watchdog),
            web.get("/watchdog", handle_watchdog),
            web.get("/test", handle_test),
            web.get("/metrics", handle_metrics),
            web.get("/healthz", handle_healthz),
        ]
    )

    async def _start(app: web.Application) -> None:
        app["deadman"] = asyncio.create_task(
            _deadman_loop(env_float("DEADMAN_STALE_SECONDS", 600.0, floor=120.0))
        )

    async def _stop(app: web.Application) -> None:
        app["deadman"].cancel()

    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)
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
