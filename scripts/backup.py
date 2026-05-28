#!/usr/bin/env python3
"""Automated SQLite backup script with encryption and integrity checking.

Copies all tenant databases to a timestamped backup directory with optional
Fernet encryption if BACKUP_ENCRYPTION_KEY is set in the environment.

Run daily via cron: 0 3 * * * /var/www/laval-digital/venv/bin/python /var/www/laval-digital/scripts/backup.py

Keeps the last 7 daily backups and 4 weekly backups.
"""

import datetime
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
BACKUP_ROOT = BASE_DIR / "backups"
DATA_DIR = BASE_DIR / "data"
DAYS_TO_KEEP = 7
WEEKS_TO_KEEP = 4

# Optional encryption key (Fernet 32-byte base64-encoded)
_ENCRYPTION_KEY = os.environ.get("BACKUP_ENCRYPTION_KEY", "")


def _get_fernet():
    """Return a Fernet cipher if BACKUP_ENCRYPTION_KEY is set, else None."""
    if not _ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(_ENCRYPTION_KEY)
    except Exception as e:
        print(f"Warning: BACKUP_ENCRYPTION_KEY set but Fernet init failed: {e}")
        return None


def _encrypt_file(src: Path, dst: Path, fernet) -> bool:
    """Encrypt src to dst using Fernet."""
    try:
        data = src.read_bytes()
        encrypted = fernet.encrypt(data)
        dst.write_bytes(encrypted)
        return True
    except Exception as e:
        print(f"Encryption failed for {src}: {e}")
        return False


def _verify_backup(src_path: Path, backup_path: Path) -> bool:
    """Verify backup integrity via PRAGMA integrity_check and page count."""
    try:
        import sqlite3
        src_conn = sqlite3.connect(str(src_path))
        src_integrity = src_conn.execute("PRAGMA integrity_check").fetchone()[0]
        src_pages = src_conn.execute("PRAGMA page_count").fetchone()[0]
        src_conn.close()

        bak_conn = sqlite3.connect(str(backup_path))
        bak_integrity = bak_conn.execute("PRAGMA integrity_check").fetchone()[0]
        bak_pages = bak_conn.execute("PRAGMA page_count").fetchone()[0]
        bak_conn.close()

        if src_integrity != "ok" or bak_integrity != "ok":
            print(f"Integrity check FAILED for {backup_path}")
            return False
        if src_pages != bak_pages:
            print(f"Page count mismatch: source={src_pages}, backup={bak_pages}")
            return False
        return True
    except Exception as e:
        print(f"Backup verification failed for {backup_path}: {e}")
        return False


def backup_sqlite(src_path: Path, dst_path: Path) -> bool:
    """Use SQLite's .backup command for safe online backup with optional encryption."""
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        if _ENCRYPTION_KEY:
            fernet = _get_fernet()
            if fernet:
                # Backup to temp path, then encrypt
                temp_path = dst_path.with_suffix(".tmp.db")
                conn = sqlite3.connect(str(src_path))
                backup_conn = sqlite3.connect(str(temp_path))
                with backup_conn:
                    conn.backup(backup_conn)
                backup_conn.close()
                conn.close()
                if not _encrypt_file(temp_path, dst_path.with_suffix(".enc"), fernet):
                    temp_path.unlink(missing_ok=True)
                    return False
                temp_path.unlink(missing_ok=True)
                return True

        # Unencrypted fallback
        conn = sqlite3.connect(str(src_path))
        backup_conn = sqlite3.connect(str(dst_path))
        with backup_conn:
            conn.backup(backup_conn)
        backup_conn.close()
        conn.close()

        # Verify integrity
        return _verify_backup(src_path, dst_path)
    except Exception as e:
        print(f"Failed to backup {src_path}: {e}")
        return False


def _safe_rmtree(path: Path) -> None:
    """Safely remove a directory tree with basic path safety check."""
    try:
        resolved = path.resolve()
        allowed = BACKUP_ROOT.resolve()
        if not str(resolved).startswith(str(allowed) + "/"):
            print(f"Refusing to remove {resolved}: outside backup root")
            return
        shutil.rmtree(path)
        print(f"Cleaned: {path}")
    except Exception as e:
        print(f"Failed to clean {path}: {e}")


def _try_parse_date(name: str):
    """Try to parse a directory name as a date, returning None on failure."""
    try:
        return datetime.datetime.strptime(name, "%Y-%m-%d")
    except ValueError:
        return None


def main():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    week_str = now.strftime("%Y-W%W")

    daily_dir = BACKUP_ROOT / "daily" / date_str
    weekly_dir = BACKUP_ROOT / "weekly" / week_str

    daily_dir.mkdir(parents=True, exist_ok=True)

    if not DATA_DIR.exists():
        print("No data directory found.")
        return

    count = 0
    errors = 0
    for db_file in sorted(DATA_DIR.rglob("*.db")):
        rel = db_file.relative_to(DATA_DIR)
        dst = daily_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if backup_sqlite(db_file, dst):
            count += 1
        else:
            errors += 1

    print(f"Backed up {count} databases to {daily_dir}" +
          (f" ({errors} errors)" if errors else ""))

    # Also copy to weekly if not already done this week
    weekly_dst = weekly_dir / date_str
    if not weekly_dst.exists():
        shutil.copytree(daily_dir, weekly_dst, dirs_exist_ok=True)
        print(f"Copied to weekly backup: {weekly_dst}")

    # Clean old daily backups
    daily_parent = BACKUP_ROOT / "daily"
    if daily_parent.exists():
        for d in sorted(daily_parent.iterdir()):
            parsed = _try_parse_date(d.name)
            if d.is_dir() and parsed and (now - parsed).days > DAYS_TO_KEEP:
                _safe_rmtree(d)

    # Clean old weekly backups
    weekly_parent = BACKUP_ROOT / "weekly"
    if weekly_parent.exists():
        weeks = sorted(weekly_parent.iterdir(), reverse=True)
        for w in weeks[WEEKS_TO_KEEP:]:
            _safe_rmtree(w)

    # Offsite sync via rsync (BACKUP_OFFSITE_DEST)
    offsite_dest = os.environ.get("BACKUP_OFFSITE_DEST", "")
    if offsite_dest:
        if not offsite_dest.strip() or len(offsite_dest.strip()) < 3:
            print("WARNING: BACKUP_OFFSITE_DEST is empty or too short, skipping offsite sync")
        elif not (":" in offsite_dest or offsite_dest.startswith("/")):
            print(f"WARNING: BACKUP_OFFSITE_DEST '{offsite_dest}' does not look like a valid rsync target, skipping")
        else:
            import subprocess
            import time
            src = str(daily_dir) + "/"
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    rc = subprocess.run(["rsync", "-a", "--delete", src, offsite_dest],
                                        timeout=120).returncode
                    if rc == 0:
                        print(f"Synced to offsite destination: {offsite_dest}")
                        break
                    print(f"Offsite sync failed (rsync exit code {rc}), attempt {attempt}/{max_attempts}")
                except subprocess.TimeoutExpired:
                    print(f"Offsite rsync timed out after 120s, attempt {attempt}/{max_attempts}")
                if attempt < max_attempts:
                    time.sleep(10 * attempt)
            else:
                print("ERROR: Offsite sync failed after all retries")


if __name__ == "__main__":
    main()
