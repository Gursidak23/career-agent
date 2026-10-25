"""Personal data lives in CAREER_HOME, outside the repository; the one-time move from backend/."""

import sqlite3
import zipfile
from pathlib import Path

import pytest

from app import home_migration
from app.config import Settings, career_home, env_file_path


def test_everything_personal_defaults_into_career_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_HOME", str(tmp_path))
    s = Settings(_env_file=env_file_path())
    assert career_home() == tmp_path.resolve()
    assert s.db_url == f"sqlite:///{tmp_path.resolve() / 'career_agent.db'}"
    assert Path(s.data_dir) == tmp_path.resolve()
    assert Path(s.linkedin.user_data_dir) == tmp_path.resolve() / "linkedin_profile"
    assert env_file_path() == tmp_path.resolve() / ".env"


def test_settings_are_read_from_the_home_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_HOME", str(tmp_path))
    monkeypatch.delenv("CAREER_SMTP__DAILY_CAP", raising=False)
    (tmp_path / ".env").write_text("CAREER_SMTP__DAILY_CAP=7\n")
    assert Settings(_env_file=env_file_path()).smtp.daily_cap == 7


def test_tests_never_see_the_real_home():
    assert "career-agent-test-home-" in str(career_home())


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    """A fake old-style backend/ folder with synthetic data, and an empty new home."""
    backend = tmp_path / "backend"
    data = backend / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "output").mkdir()
    (data / "uploads" / "resume_1.pdf").write_bytes(b"%PDF-1.4 upload")
    (data / "output" / "resume_1.pdf").write_bytes(b"%PDF-1.4 tailored")
    (data / "worker.lock").write_text("123")
    db = sqlite3.connect(backend / "career_agent.db")
    db.execute("CREATE TABLE tailorings (id INTEGER PRIMARY KEY, pdf_path TEXT)")
    db.execute("CREATE TABLE resumes (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO tailorings VALUES (1, 'data/output/resume_1.pdf'), (2, NULL)")
    db.execute("INSERT INTO resumes VALUES (1, 'Sample Person')")
    db.commit()
    db.close()
    (backend / ".env").write_bytes(
        b"CAREER_LLM__GEMINI_API_KEY=test-key\r\nCAREER_DB_URL=sqlite:///./career_agent.db\r\n"
        b"CAREER_DATA_DIR=./data\r\nCAREER_SMTP__DAILY_CAP=9\r\n"
    )
    monkeypatch.setattr(home_migration, "BACKEND_DIR", backend)
    monkeypatch.setattr(home_migration, "LEGACY_DB", backend / "career_agent.db")
    monkeypatch.setattr(home_migration, "LEGACY_DATA", data)
    monkeypatch.setattr(home_migration, "LEGACY_ENV", backend / ".env")
    monkeypatch.setattr(home_migration, "_app_running", lambda: False)
    return backend, tmp_path / "home"


def test_migration_moves_verifies_and_removes_the_originals(legacy):
    backend, home = legacy
    assert {kind for kind, _ in home_migration.legacy_items()} == {"database", "data", "settings"}

    moved = home_migration.migrate(home)

    assert len(moved) == 4
    assert (home / "uploads" / "resume_1.pdf").read_bytes() == b"%PDF-1.4 upload"
    assert (home / "output" / "resume_1.pdf").read_bytes() == b"%PDF-1.4 tailored"
    db = sqlite3.connect(home / "career_agent.db")
    assert db.execute("SELECT name FROM resumes").fetchone() == ("Sample Person",)
    # Stored paths now point at the moved file.
    assert db.execute("SELECT pdf_path FROM tailorings WHERE id = 1").fetchone() == (str(home / "output" / "resume_1.pdf"),)
    db.close()
    env = (home / ".env").read_bytes()
    assert b"CAREER_LLM__GEMINI_API_KEY=test-key\r\n" in env
    assert b"# Moved to CAREER_HOME by migrate-home: CAREER_DB_URL=" in env
    assert b"# Moved to CAREER_HOME by migrate-home: CAREER_DATA_DIR=" in env
    assert (home / ".env").stat().st_mode & 0o777 == 0o600
    # The originals are gone from the repository, and a backup of them exists.
    assert not (backend / "career_agent.db").exists()
    assert not (backend / "data").exists()
    assert not (backend / ".env").exists()
    assert home_migration.legacy_items() == []
    (backup,) = (home / "backups").glob("pre-move-*.zip")
    with zipfile.ZipFile(backup) as zf:
        assert {"career_agent.db", ".env", "data/uploads/resume_1.pdf"} <= set(zf.namelist())


def test_migration_never_overwrites_an_existing_home(legacy):
    backend, home = legacy
    home.mkdir()
    (home / "career_agent.db").write_bytes(b"newer data")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        home_migration.migrate(home)
    assert (backend / "career_agent.db").exists()
    assert (home / "career_agent.db").read_bytes() == b"newer data"


def test_migration_refuses_while_the_app_runs(legacy, monkeypatch):
    backend, home = legacy
    monkeypatch.setattr(home_migration, "_app_running", lambda: True)
    with pytest.raises(RuntimeError, match="running"):
        home_migration.migrate(home)
    assert (backend / "career_agent.db").exists()


def test_nothing_to_move_is_a_no_op(legacy, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    monkeypatch.setattr(home_migration, "LEGACY_DB", empty / "career_agent.db")
    monkeypatch.setattr(home_migration, "LEGACY_DATA", empty / "data")
    monkeypatch.setattr(home_migration, "LEGACY_ENV", empty / ".env")
    assert home_migration.migrate(tmp_path / "home") == []
