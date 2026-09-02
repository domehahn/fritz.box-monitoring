#!/usr/bin/env python3
"""Static checks for the provisioned Grafana dashboards.

Catches the mistakes that only show up as an empty panel at 2 a.m.:
  * a datasource uid that does not match a provisioned datasource
  * a leftover ``${DS_...}`` / ``$__inputs`` export placeholder
  * a data panel with no targets, or a target with an empty expr
  * a template ``query`` variable pointing at an unknown datasource
  * duplicate dashboard uids or duplicate panel ids

Exit 1 on any problem. Run: ``python3 scripts/lint-dashboards.py``.
"""
from __future__ import annotations

import glob
import json
import os
import sys

DASH_DIR = "config/grafana/provisioning/dashboards_files"

# uids provisioned in config/grafana/provisioning/datasources/
ALLOWED_DS_UIDS = {"prometheus", "loki", "victoriametrics"}
# Grafana's built-in datasource sentinels
BUILTIN_DS = {"-- Grafana --", "-- Mixed --", "-- Dashboard --", "grafana", None, ""}

# panel types that legitimately have no query
NO_QUERY_TYPES = {"row", "text", "dashlist", "news", "welcome", "alertlist", "annolist"}


def _ds_uid(ds: object) -> object:
    """A datasource ref is either a {'type','uid'} dict or a bare string name."""
    if isinstance(ds, dict):
        return ds.get("uid")
    return ds


def check_dashboard(path: str, problems: list[str], uids: dict[str, str]) -> None:
    name = os.path.basename(path)
    with open(path) as fh:
        raw = fh.read()
    doc = json.loads(raw)

    uid = doc.get("uid")
    if not uid:
        problems.append(f"{name}: no dashboard uid")
    elif uid in uids:
        problems.append(f"{name}: duplicate dashboard uid {uid!r} (also {uids[uid]})")
    else:
        uids[uid] = name

    if "${DS_" in raw or "$__inputs" in raw or '"__inputs"' in raw:
        problems.append(f"{name}: unresolved export placeholder (${{DS_}} / __inputs)")

    seen_ids: set[int] = set()

    def walk_panels(panels: list, row: str = "") -> None:
        for p in panels:
            pid = p.get("id")
            if pid is not None:
                if pid in seen_ids:
                    problems.append(f"{name}: duplicate panel id {pid}")
                seen_ids.add(pid)
            ptype = p.get("type", "")
            title = p.get("title") or f"id={pid}"
            if p.get("panels"):  # a collapsed row
                walk_panels(p["panels"], row=title)
                continue
            if ptype in NO_QUERY_TYPES:
                continue

            targets = p.get("targets") or []
            if not targets:
                problems.append(f"{name}: panel {title!r} ({ptype}) has no targets")
                continue
            for t in targets:
                uidv = _ds_uid(t.get("datasource", p.get("datasource")))
                if uidv not in ALLOWED_DS_UIDS and uidv not in BUILTIN_DS:
                    problems.append(
                        f"{name}: panel {title!r} target {t.get('refId')} "
                        f"-> unknown datasource uid {uidv!r}"
                    )
                expr = (t.get("expr") or t.get("query") or "").strip()
                # blackbox/testdata panels and hidden rows may legitimately be empty
                if not expr and not t.get("hide"):
                    problems.append(
                        f"{name}: panel {title!r} target {t.get('refId')} has empty expr"
                    )

    walk_panels(doc.get("panels", []))

    for var in (doc.get("templating") or {}).get("list", []):
        if var.get("type") == "query":
            uidv = _ds_uid(var.get("datasource"))
            if uidv not in ALLOWED_DS_UIDS and uidv not in BUILTIN_DS:
                problems.append(
                    f"{name}: template var ${var.get('name')} "
                    f"-> unknown datasource uid {uidv!r}"
                )


def main() -> int:
    files = sorted(glob.glob(f"{DASH_DIR}/*.json"))
    if not files:
        print(f"no dashboards under {DASH_DIR}", file=sys.stderr)
        return 1
    problems: list[str] = []
    uids: dict[str, str] = {}
    for f in files:
        try:
            check_dashboard(f, problems, uids)
        except json.JSONDecodeError as exc:
            problems.append(f"{os.path.basename(f)}: invalid JSON — {exc}")
    if problems:
        print("\n".join(f"  ✗ {p}" for p in problems))
        print(f"\n{len(problems)} problem(s) in {len(files)} dashboard(s).")
        return 1
    print(f"  ✓ {len(files)} dashboards OK — {len(uids)} unique uids, datasources & queries valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
