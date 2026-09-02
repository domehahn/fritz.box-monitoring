"""The only place that writes to a real device.

Both functions are best-effort: they return ``(ok, detail)`` and never raise, so
a flaky bridge can't take the loop down. They are called **only** when
``AUTOMATION_DRY_RUN`` is false.
"""
from __future__ import annotations

from typing import Any, Tuple

from loguru import logger

HTTP_TIMEOUT_S = 10.0


def apply_bosch_setpoints(host: str, cert: str, key: str, celsius: float) -> Tuple[bool, str]:
    """Set every RoomClimateControl setpoint on the SHC to ``celsius``."""
    try:
        from boschshcpy import SHCSession
    except Exception as exc:  # noqa: BLE001
        return False, f"boschshcpy missing: {exc}"
    try:
        session: Any = SHCSession(host, cert, key)
        session.authenticate()
        n = 0
        for dev in getattr(session, "devices", []) or []:
            for svc in getattr(dev, "device_services", []) or []:
                if str(getattr(svc, "id", "")).lower() != "roomclimatecontrol":
                    continue
                # boschshcpy service objects expose put_state_element(name, value)
                put = getattr(svc, "put_state_element", None)
                if callable(put):
                    put("setpointTemperature", round(float(celsius), 1))
                    n += 1
        return (n > 0), f"{n} room(s) set to {celsius:.1f}°C"
    except Exception as exc:  # noqa: BLE001
        logger.warning("bosch setpoint write failed: {}", exc)
        return False, str(exc)


def apply_hue_all_off(host: str, app_key: str) -> Tuple[bool, str]:
    """Turn every Hue ``grouped_light`` off via the local CLIP v2 API."""
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    base = f"https://{host}/clip/v2/resource"
    hdr = {"hue-application-key": app_key}
    try:
        s = requests.Session()
        s.verify = False  # bridge serves a self-signed cert
        groups = s.get(f"{base}/grouped_light", headers=hdr, timeout=HTTP_TIMEOUT_S)
        groups.raise_for_status()
        ids = [g["id"] for g in groups.json().get("data", [])]
        n = 0
        for gid in ids:
            r = s.put(
                f"{base}/grouped_light/{gid}",
                headers=hdr,
                json={"on": {"on": False}},
                timeout=HTTP_TIMEOUT_S,
            )
            if r.ok:
                n += 1
        return (n > 0), f"{n}/{len(ids)} group(s) off"
    except Exception as exc:  # noqa: BLE001
        logger.warning("hue all-off failed: {}", exc)
        return False, str(exc)
