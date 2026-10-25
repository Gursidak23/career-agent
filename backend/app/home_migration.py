"""One-time move of personal data out of the repository into CAREER_HOME.

Older versions kept the database, uploads, generated resumes, backups and .env
inside backend/, guarded only by .gitignore. `career-agent migrate-home` moves
them to career_home(): it zips the originals first, copies, verifies the copy
(row counts, checksums), and only then deletes the in-repo files.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
LEGACY_DB = BACKEND_DIR / "career_agent.db"
LEGACY_DATA = BACKEND_DIR / "data"
LEGACY_ENV = BACKEND_DIR / ".env"

# .env keys whose old relative values pointed into backend/; the new defaults
# already point into CAREER_HOME, so the moved .env comments them out.
_PATH_KEYS = ("CAREER_DB_URL", "CAREER_DATA_DIR", "CAREER_LINKEDIN__USER_DATA_DIR")


def legacy_items() -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    if LEGACY_DB.exists():
        items.append(("database", LEGACY_DB))
    if LEGACY_DATA.is_dir() and any(p.name != "worker.lock" for p in LEGACY_DATA.iterdir()):
        items.append(("data", LEGACY_DATA))
    if LEGACY_ENV.exists():
        items.append(("settings", LEGACY_ENV))
    return items


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _app_running() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", 8000)) == 0


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def _relocate(stored: str, home: Path) -> str | None:
    """New location for a file path stored in the database, or None to leave it."""
    path = Path(stored)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    path = Path(os.path.normpath(path))
    try:
        return str(home / path.relative_to(LEGACY_DATA))
    except ValueError:
        return None


def _move_database(home: Path) -> str:
    target = home / "career_agent.db"
    src = sqlite3.connect(LEGACY_DB)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        before = _table_counts(src)
        if "tailorings" in before:
            rows = dst.execute("SELECT id, pdf_path FROM tailorings WHERE pdf_path IS NOT NULL").fetchall()
            for row_id, stored in rows:
                new = _relocate(stored, home)
                if new:
                    dst.execute("UPDATE tailorings SET pdf_path = ? WHERE id = ?", (new, row_id))
            dst.commit()
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("the copied database failed SQLite's integrity check")
        after = _table_counts(dst)
        if after != before:
            raise RuntimeError(f"row counts differ after copying the database: {before} vs {after}")
    finally:
        dst.close()
        src.close()
    return f"database ({sum(before.values())} rows in {len(before)} tables)"


def _move_data(home: Path) -> str:
    copied = 0
    for src in sorted(LEGACY_DATA.rglob("*")):
        if src.is_dir() or src.name == "worker.lock":
            continue
        dst = home / src.relative_to(LEGACY_DATA)
        if dst.exists():
            raise RuntimeError(f"{dst} already exists; not overwriting it")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if _sha256(src) != _sha256(dst):
            raise RuntimeError(f"checksum mismatch after copying {src.name}")
        copied += 1
    return f"{copied} files (uploads, generated resumes, backups, caches)"


def _move_env(home: Path) -> str:
    target = home / ".env"
    if target.exists():
        raise RuntimeError(f"{target} already exists; merge {LEGACY_ENV} into it by hand")
    out: list[bytes] = []
    for line in LEGACY_ENV.read_bytes().splitlines(keepends=True):
        key = line.split(b"=", 1)[0].strip().decode("utf-8", "replace")
        if key in _PATH_KEYS:
            line = b"# Moved to CAREER_HOME by migrate-home: " + line
        out.append(line)
    target.write_bytes(b"".join(out))
    target.chmod(0o600)
    return ".env (your keys and settings)"


def migrate(home: Path) -> list[str]:
    """Move everything legacy_items() finds into `home`. Returns what was moved."""
    items = legacy_items()
    if not items:
        return []
    if _app_running():
        raise RuntimeError("Career Agent is running (port 8000 is in use). Stop it, then run this again.")
    if (home / "career_agent.db").exists() and LEGACY_DB.exists():
        raise RuntimeError(f"{home / 'career_agent.db'} already exists; refusing to overwrite it")

    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)

    # 1. Untouched copy of every original file, before anything changes.
    backup = home / "backups" / f"pre-move-{datetime.now():%Y%m%d-%H%M%S}.zip"
    backup.parent.mkdir(parents=True, exist_ok=True)
    originals = [LEGACY_DB, LEGACY_DB.with_name(LEGACY_DB.name + "-wal"), LEGACY_DB.with_name(LEGACY_DB.name + "-shm"), LEGACY_ENV]
    with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in originals:
            if f.exists():
                zf.write(f, f.relative_to(BACKEND_DIR))
        if LEGACY_DATA.is_dir():
            for f in sorted(LEGACY_DATA.rglob("*")):
                if f.is_file() and f.name != "worker.lock":
                    zf.write(f, f.relative_to(BACKEND_DIR))

    # 2. Copy and verify. Data first, so the database's rewritten paths resolve.
    moved: list[str] = []
    if LEGACY_DATA.is_dir():
        moved.append(_move_data(home))
    if LEGACY_DB.exists():
        moved.append(_move_database(home))
    if LEGACY_ENV.exists():
        moved.append(_move_env(home))

    # 3. Everything verified: remove the in-repo originals.
    for f in originals:
        f.unlink(missing_ok=True)
    if LEGACY_DATA.is_dir():
        shutil.rmtree(LEGACY_DATA)
    moved.append(f"backup of the originals: {backup}")
    return moved
