#!/usr/bin/env python3
"""Automated SQLite backup script.

Copies all tenant databases to a timestamped backup directory.
Run daily via cron: 0 3 * * * /var/www/laval-digital/venv/bin/python /var/www/laval-digital/scripts/backup.py

Keeps the last 7 daily backups and 4 weekly backups.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
BACKUP_ROOT = BASE_DIR / "backups"
TENANTS_DIR = BASE_DIR / "tenants"
DAYS_TO_KEEP = 7
WEEKS_TO_KEEP = 4


def backup_sqlite(src_path: Path, dst_path: Path) -> bool:
    """Use SQLite's .backup command for safe online backup."""
    try:
        subprocess.run(
            ["sqlite3", str(src_path), f".backup '{dst_path}'"],
            capture_output=True, timeout=30, check=True,
        )
        return True
    except Exception as e:
        print(f"Failed to backup {src_path}: {e}")
        return False


def main():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    week_str = now.strftime("%Y-W%W")

    daily_dir = BACKUP_ROOT / "daily" / date_str
    weekly_dir = BACKUP_ROOT / "weekly" / week_str

    daily_dir.mkdir(parents=True, exist_ok=True)

    if not TENANTS_DIR.exists():
        print("No tenants directory found.")
        return

    count = 0
    for db_file in sorted(TENANTS_DIR.rglob("*.db")):
        rel = db_file.relative_to(TENANTS_DIR)
        dst = daily_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if backup_sqlite(db_file, dst):
            count += 1

    print(f"Backed up {count} databases to {daily_dir}")

    # Also copy to weekly if not already done this week
    weekly_dst = weekly_dir / date_str
    if not weekly_dst.exists():
        shutil.copytree(daily_dir, weekly_dst, dirs_exist_ok=True)
        print(f"Copied to weekly backup: {weekly_dst}")

    # Clean old daily backups
    for d in sorted((BACKUP_ROOT / "daily").iterdir()):
        if d.is_dir() and (now - datetime.datetime.strptime(d.name, "%Y-%m-%d")).days > DAYS_TO_KEEP:
            shutil.rmtree(d)
            print(f"Cleaned old daily backup: {d}")

    # Clean old weekly backups
    weeks = sorted((BACKUP_ROOT / "weekly").iterdir(), reverse=True)
    for w in weeks[WEEKS_TO_KEEP:]:
        shutil.rmtree(w)
        print(f"Cleaned old weekly backup: {w}")


if __name__ == "__main__":
    main()
