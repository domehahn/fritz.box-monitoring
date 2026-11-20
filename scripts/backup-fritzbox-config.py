#!/usr/bin/env python3
"""FRITZ!Box Configuration Backup Vault.

Automated, encrypted TR-064 backup utility for FRITZ!OS configurations.
Fetches encrypted .export files via DeviceConfig:1 (X_AVM-DE_CreateConfigFile)
and rotates old snapshots according to retention policies.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FRITZ!Box Encrypted Configuration Vault & Automated Backup"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("FRITZ_IP", os.getenv("FRITZ_HOST", "192.168.178.1")),
        help="FRITZ!Box IP or hostname (default: 192.168.178.1 or $FRITZ_IP)",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("FRITZ_USER", ""),
        help="FRITZ!Box username (default: $FRITZ_USER)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("FRITZ_PASSWORD", ""),
        help="FRITZ!Box admin password (default: $FRITZ_PASSWORD)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("FRITZ_BACKUP_DIR", "backups/fritzbox_configs"),
        help="Destination directory for .export backups",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.getenv("FRITZ_BACKUP_RETENTION_DAYS", "30")),
        help="Number of days to retain backups before rotation (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform configuration check without triggering export",
    )
    return parser.parse_args()


def rotate_old_backups(backup_dir: Path, retention_days: int) -> int:
    """Removes backups older than retention_days."""
    if retention_days <= 0 or not backup_dir.exists():
        return 0

    now = time.time()
    cutoff_seconds = retention_days * 86400
    removed_count = 0

    for path in backup_dir.glob("fritzbox_backup_*.export"):
        try:
            mtime = path.stat().st_mtime
            if (now - mtime) > cutoff_seconds:
                path.unlink()
                removed_count += 1
                print(f"[vault] Rotated expired backup: {path.name}")
        except OSError as exc:
            print(f"[vault] Error rotating {path.name}: {exc}", file=sys.stderr)

    return removed_count


def backup_fritzbox(host: str, user: str, password: str, output_dir: Path, dry_run: bool = False) -> Path:
    if not password:
        raise ValueError("FRITZ!Box password is required to encrypt configuration export.")

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_path = output_dir / f"fritzbox_backup_{timestamp}.export"

    if dry_run:
        print(f"[dry-run] Would trigger X_AVM-DE_CreateConfigFile on {host} -> {target_path}")
        return target_path

    # Attempt connection via fritzconnection if available, else raw TR-064 SOAP
    try:
        from fritzconnection import FritzConnection

        fc = FritzConnection(address=host, user=user, password=password, timeout=15.0)
        res = fc.call_action(
            "DeviceConfig1",
            "X_AVM-DE_CreateConfigFile",
            NewX_AVM-DE_Password=password,
        )
        download_url = res.get("NewX_AVM-DE_ConfigFileUrl")
    except ImportError:
        # Fallback to fritz_avm_client
        from fritz_avm_client import FritzClient, Settings

        settings = Settings(host=host, user=user, password=password, timeout=15)
        client = FritzClient(settings)
        fc = getattr(client, "fc", None) or getattr(client, "connection", None)
        if not fc:
            raise RuntimeError("Could not establish TR-064 connection for backup.")
        res = fc.call_action(
            "DeviceConfig1",
            "X_AVM-DE_CreateConfigFile",
            NewX_AVM-DE_Password=password,
        )
        download_url = res.get("NewX_AVM-DE_ConfigFileUrl")

    if not download_url:
        raise RuntimeError("FRITZ!Box did not return a valid configuration download URL.")

    # In case URL is relative or uses local hostname
    if not download_url.startswith("http"):
        download_url = f"https://{host}:49443/{download_url.lstrip('/')}"

    print(f"[vault] Config generated. Downloading encrypted export from {download_url}...")
    
    # Download file using digest/basic auth
    auth = requests.auth.HTTPDigestAuth(user, password) if user else None
    resp = requests.get(download_url, auth=auth, verify=False, timeout=60.0)
    if resp.status_code == 401 and user:
        # Retry with Basic auth
        resp = requests.get(
            download_url,
            auth=requests.auth.HTTPBasicAuth(user, password),
            verify=False,
            timeout=60.0,
        )

    resp.raise_for_status()

    target_path.write_bytes(resp.content)
    size_kb = len(resp.content) / 1024.0
    print(f"[vault] Successfully archived encrypted backup: {target_path} ({size_kb:.1f} KB)")
    return target_path


def main() -> None:
    args = parse_args()
    backup_dir = Path(args.output_dir)

    print(f"[vault] Initializing FRITZ!Box configuration backup vault ({args.host})...")
    try:
        backup_fritzbox(
            host=args.host,
            user=args.user,
            password=args.password,
            output_dir=backup_dir,
            dry_run=args.dry_run,
        )
        rotated = rotate_old_backups(backup_dir, args.retention_days)
        if rotated:
            print(f"[vault] Retention policy applied: removed {rotated} older backup(s).")
        print("[vault] Backup run completed successfully.")
    except Exception as exc:
        print(f"[vault] Error executing backup: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
