"""Build the weekly digest text from Prometheus / Loki queries.

:func:`build_report` is pure: it takes a ``query(expr) -> float|None`` callable
(and an optional ``query_vec`` for label context) so it is unit-testable with a
fake backend.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

Scalar = Callable[[str], Optional[float]]
Vector = Callable[[str], List[Tuple[dict, float]]]


def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v * 100:.2f}%"


def _gb(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v / 1e6:.0f} MB" if v < 1e9 else f"{v / 1e9:.1f} GB"


def _eur(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.3f} €"


def _dur(sec: Optional[float]) -> str:
    if sec is None:
        return "n/a"
    d, h = divmod(int(sec // 3600), 24)
    return f"{d}d {h}h" if d else f"{h}h"


def build_report(q: Scalar, qv: Vector, window: str = "7d") -> Tuple[str, str]:
    """Return (title, markdown_body)."""
    L: List[str] = []

    score = q(f"avg_over_time(home:network_health:score[{window}])")
    score_min = q(f"min_over_time(home:network_health:score[{window}])")
    internet = q(f"avg_over_time(home:health:internet_reachability[{window}])")
    L.append(f"**Network health** — avg {_pct(score)}, worst {_pct(score_min)}")
    L.append(f"**Internet reachable** — {_pct(internet)} of the week")

    loss = q(f"max(max_over_time(fritz:probe_loss_ratio:5m[{window}]))")
    if loss and loss > 0.02:
        L.append(f"**Worst packet loss** — {_pct(loss)} (see Network Path Probes)")

    dns = q(f"avg_over_time(home:health:dns[{window}])")
    if dns is not None and dns < 0.999:
        L.append(f"**DNS availability** — {_pct(dns)}")

    talkers = qv(
        f"topk(3, sum by (ip) (increase(lantap_host_received_bytes_total[{window}])))"
    )
    names = {m.get("ip"): m.get("name") for m, _ in qv("lantap_host_info")}
    if talkers:
        L.append("**Top bandwidth (download, week):**")
        for m, v in talkers:
            ip = m.get("ip", "?")
            L.append(f"  • {names.get(ip) or ip} — {_gb(v)}")

    price = q(f"avg_over_time(energy_price_eur_per_kwh[{window}])")
    if price is not None:
        L.append(f"**Electricity** — avg {_eur(price)}/kWh")
    kwh = q(f"increase(energy_import_watt_hours_total[{window}]) / 1000")
    if kwh:
        cost = (kwh * price) if price else None
        L.append(
            f"**Metered consumption** — {kwh:.0f} kWh"
            + (f" (~{_eur(cost)})" if cost else "")
        )

    fired = q(
        f'count(count by (alertname) (max_over_time(ALERTS{{alertstate="firing"}}[{window}])))'
    )
    if fired:
        top_alerts = qv(
            f'topk(5, count by (alertname) (max_over_time(ALERTS{{alertstate="firing"}}[{window}])))'
        )
        L.append(f"**Alerts fired** — {int(fired)} distinct:")
        for m, _ in top_alerts:
            L.append(f"  • {m.get('alertname', '?')}")
    else:
        L.append("**Alerts fired** — none 🎉")

    disk_days = q(
        "min(predict_linear(node_filesystem_avail_bytes"
        '{fstype!~"tmpfs|overlay|squashfs"}[24h], 30*24*3600) '
        '/ node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"})'
    )
    if disk_days is not None and disk_days < 0.5:
        L.append("**Disk** — projected to fill within a month ⚠️")

    bage = q("time() - backup_last_success_timestamp_seconds")
    bsize = q("backup_repository_bytes")
    L.append(f"**Backup** — last {_dur(bage)} ago, repo {_gb(bsize)}")

    title = f"📊 Weekly network digest — health {_pct(score)}"
    return title, "\n".join(L)
