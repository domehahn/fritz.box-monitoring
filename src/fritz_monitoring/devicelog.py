"""Ship the FRITZ!Box event log into Loki as structured events.

The box keeps its own event log (``DeviceInfo1:GetDeviceLog`` — WAN reconnects,
Wi-Fi logins, DECT pairings, port-forward hits, firmware events). With the
least-privilege account this action returns 401; once the monitoring user has
the "FRITZ!Box Einstellungen" permission it works, so this is an opt-in
companion to the snapshot-derived events in :mod:`fritz_monitoring.events`.

Only *new* lines since the previous poll are emitted, on the same ``events``
logger channel (JSON, ``event_type="fritzbox_log"``) that Alloy already ships to
Loki. The first poll after start only establishes the baseline.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, List, Optional, Set

from loguru import logger

_LINE = re.compile(r"^\s*(\d{2}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.*\S)\s*$")

#: substring -> subsystem, checked in order (first match wins)
_SUBSYSTEM_HINTS = (
    ("Internetverbindung", "wan"),
    ("PPPoE", "wan"),
    ("IPv6", "wan"),
    ("DSL", "wan"),
    ("Zeitüberschreitung", "wan"),
    ("Anmeldung des Internetzugang", "wan"),
    ("WLAN", "wifi"),
    ("Funknetz", "wifi"),
    ("WPS", "wifi"),
    ("DECT", "dect"),
    ("Schnurlostelefon", "dect"),
    ("Anmeldung", "security"),
    ("angemeldet", "security"),
    ("Kennwort", "security"),
    ("Portfreigabe", "security"),
    ("MyFRITZ", "security"),
    ("VPN", "security"),
    ("Update", "system"),
    ("Neustart", "system"),
    ("Stromausfall", "system"),
    ("USB", "system"),
)
_WARN_HINTS = (
    "getrennt",
    "Zeitüberschreitung",
    "fehlgeschlagen",
    "nicht möglich",
    "Fehler",
    "abgewiesen",
    "ungültig",
)


def _classify(msg: str) -> str:
    for needle, subsystem in _SUBSYSTEM_HINTS:
        if needle.lower() in msg.lower():
            return subsystem
    return "system"


def _severity(msg: str) -> str:
    low = msg.lower()
    return "warning" if any(h.lower() in low for h in _WARN_HINTS) else "info"


def parse_log(raw: str) -> List[dict]:
    """Parse a ``GetDeviceLog`` blob (newest line first) into event dicts."""
    events: List[dict] = []
    for line in (raw or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        date_s, time_s, msg = m.groups()
        try:
            ts = datetime.strptime(f"{date_s} {time_s}", "%d.%m.%y %H:%M:%S")
            ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)
        events.append(
            {
                "timestamp": ts.isoformat(),
                "event_type": "fritzbox_log",
                "subsystem": _classify(msg),
                "severity": _severity(msg),
                "message": msg,
            }
        )
    return events


class DeviceLogTailer:
    """Poll the box log at most every ``min_interval_s`` and emit new lines."""

    MAX_SEEN = 2000

    def __init__(self, min_interval_s: float = 300.0) -> None:
        self.min_interval_s = min_interval_s
        self._seen: Set[str] = set()
        self._seen_order: List[str] = []
        self._primed = False
        self._last_poll: Optional[datetime] = None

    def _remember(self, key: str) -> None:
        self._seen.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > self.MAX_SEEN:
            drop = self._seen_order[: len(self._seen_order) - self.MAX_SEEN]
            self._seen_order = self._seen_order[len(drop) :]
            self._seen.difference_update(drop)

    def _fetch(self, client: Any) -> str:
        fc = getattr(client, "fc", None) or getattr(client, "_fc", None)
        if fc is None or not hasattr(fc, "call_action"):
            raise RuntimeError("FritzClient exposes no fritzconnection handle")
        res = fc.call_action("DeviceInfo1", "GetDeviceLog")
        return str(res.get("NewDeviceLog", "") if isinstance(res, dict) else res or "")

    def poll(self, client: Any, now: Optional[datetime] = None) -> List[dict]:
        now = now or datetime.now(timezone.utc)
        if (
            self._last_poll
            and (now - self._last_poll).total_seconds() < self.min_interval_s
        ):
            return []
        self._last_poll = now
        try:
            raw = self._fetch(client)
        except Exception as exc:  # noqa: BLE001 - permission / transient
            logger.debug("device log poll failed: {}", exc)
            return []

        fresh: List[dict] = []
        for ev in parse_log(raw):
            key = f"{ev['timestamp']}|{ev['message']}"
            if key in self._seen:
                continue
            self._remember(key)
            if self._primed:
                fresh.append(ev)
        self._primed = True

        for ev in fresh:
            logger.bind(events=True).log(
                "WARNING" if ev["severity"] == "warning" else "INFO",
                "fritz_event {}",
                json.dumps(ev, ensure_ascii=False, sort_keys=True),
            )
        if fresh:
            logger.info("shipped {} new FRITZ!Box log line(s) to Loki", len(fresh))
        return fresh
