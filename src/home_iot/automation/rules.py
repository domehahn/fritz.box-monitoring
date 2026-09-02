"""Pure rule engine for the home-automation service.

Everything here is side-effect free and unit-tested: given a :class:`Snapshot`
of a few Prometheus values, per-rule cooldown state, and ``now``, :func:`evaluate`
returns the list of :class:`Decision` objects the caller should act on (or, in
dry-run, just log).

Rules are intentionally few and conservative — this can move a real radiator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class Snapshot:
    """A handful of Prometheus values. ``None`` = the query returned nothing."""

    occupied_now: Optional[float] = None
    #: max of home:occupied:bool over the "away" window — 0.0 ⇒ empty the whole time
    occupied_window_max: Optional[float] = None
    valve_max: Optional[float] = None
    setpoint_min: Optional[float] = None
    setpoint_max: Optional[float] = None
    lights_on: Optional[float] = None


@dataclass(frozen=True)
class Tunables:
    away_minutes: int = 45
    setback_c: float = 17.0
    comfort_c: float = 21.0
    lights_away_minutes: int = 20


@dataclass(frozen=True)
class Action:
    kind: str  # "bosch_setpoints" | "hue_all_off"
    params: Dict[str, float] = field(default_factory=dict)
    human: str = ""


@dataclass(frozen=True)
class Decision:
    rule: str
    reason: str
    action: Action


@dataclass(frozen=True)
class Rule:
    name: str
    cooldown_s: float
    #: (snapshot, tun) -> reason string if it should fire, else None
    check: Callable[[Snapshot, Tunables], Optional[str]]
    build: Callable[[Snapshot, Tunables], Action]


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #
def _away_setback_check(s: Snapshot, t: Tunables) -> Optional[str]:
    win, valve, sp = s.occupied_window_max, s.valve_max, s.setpoint_max
    if win is None or valve is None or sp is None:
        return None
    if win == 0.0 and valve > 15.0 and sp > t.setback_c + 0.5:
        return (
            f"nobody home for {t.away_minutes} min and radiators still warm "
            f"(valve {valve:.0f}%, setpoint {sp:.1f}°C)"
        )
    return None


def _away_setback_build(s: Snapshot, t: Tunables) -> Action:
    return Action(
        "bosch_setpoints",
        {"celsius": t.setback_c},
        f"set every room climate control to {t.setback_c:.0f}°C",
    )


def _home_restore_check(s: Snapshot, t: Tunables) -> Optional[str]:
    occ, sp = s.occupied_now, s.setpoint_min
    if occ is None or sp is None:
        return None
    if occ >= 1.0 and sp <= t.setback_c + 0.5:
        return f"someone is home and rooms are still at the {t.setback_c:.0f}°C setback"
    return None


def _home_restore_build(s: Snapshot, t: Tunables) -> Action:
    return Action(
        "bosch_setpoints",
        {"celsius": t.comfort_c},
        f"restore every room climate control to {t.comfort_c:.0f}°C",
    )


def _lights_off_check(s: Snapshot, t: Tunables) -> Optional[str]:
    win, lights = s.occupied_window_max, s.lights_on
    if win is None or lights is None:
        return None
    if win == 0.0 and lights >= 1.0:
        return (
            f"nobody home for {t.lights_away_minutes} min and "
            f"{lights:.0f} Hue light(s) still on"
        )
    return None


def _lights_off_build(s: Snapshot, t: Tunables) -> Action:
    return Action("hue_all_off", {}, "turn off all Hue lights")


RULES: List[Rule] = [
    Rule("away_heating_setback", 1800.0, _away_setback_check, _away_setback_build),
    Rule("home_heating_restore", 900.0, _home_restore_check, _home_restore_build),
    Rule("away_lights_off", 900.0, _lights_off_check, _lights_off_build),
]


def evaluate(
    snap: Snapshot,
    last_fired: Dict[str, float],
    now: float,
    tun: Optional[Tunables] = None,
    rules: Optional[List[Rule]] = None,
) -> List[Decision]:
    """Return the decisions to act on. ``last_fired`` maps rule name -> ts."""
    tun = tun or Tunables()
    out: List[Decision] = []
    for rule in rules or RULES:
        if now - last_fired.get(rule.name, 0.0) < rule.cooldown_s:
            continue
        reason = rule.check(snap, tun)
        if reason:
            out.append(Decision(rule.name, reason, rule.build(snap, tun)))
    return out
