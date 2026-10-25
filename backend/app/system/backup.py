"""Backups: a consistent copy of the database plus your uploaded resumes.

Uses SQLite's online backup API, so it is safe while the API and worker run.
Each backup is one zip in data/backups; the newest `keep` are retained.
Generated PDFs/DOCX are not included: they can be re-rendered from the database.
"""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..db import engine


def backups_dir() -> Path:
    path = get_settings().data_path / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(keep: int = 14) -> Path:
    db_path = engine.url.database
    if not db_path:
        raise RuntimeError("Backups need a file-based SQLite database")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir() / f"career-agent-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "career_agent.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, "career_agent.db")
            uploads = get_settings().uploads_path
            for f in sorted(uploads.glob("*.pdf")):
                zf.write(f, f"uploads/{f.name}")
    for old in sorted(backups_dir().glob("career-agent-*.zip"))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def list_backups() -> list[dict]:
    return [
        {
            "name": p.name,
            "size": p.stat().st_size,
            # Timezone-aware, so the UI shows local time correctly.
            "created_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        for p in sorted(backups_dir().glob("career-agent-*.zip"), reverse=True)
    ]
