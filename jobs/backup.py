import sqlite3
from datetime import datetime
from pathlib import Path

from core import config
from core.db import get_setting


def db_path() -> Path:
    return Path(config.DB_URL.replace("sqlite:///", ""))


def last_backup() -> datetime | None:
    folder = Path(get_setting("backup_dir"))
    files = sorted(folder.glob("portfolio_*.db")) if folder.exists() else []
    return datetime.fromtimestamp(files[-1].stat().st_mtime) if files else None


def run() -> Path:
    folder = Path(get_setting("backup_dir"))
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"portfolio_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    keep = int(get_setting("backup_keep") or 8)
    for old in sorted(folder.glob("portfolio_*.db"))[:-keep]:
        old.unlink()
    return dest
