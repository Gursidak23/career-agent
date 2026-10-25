"""scripts/check_personal_data.py: blocks your own details, allows made-up ones. All data here is fictional."""

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_personal_data.py"
_spec = importlib.util.spec_from_file_location("check_personal_data", _SCRIPT)
check = sys.modules["check_personal_data"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

PUBLIC = [re.compile(r"(?<![a-z0-9.@])(?:(?:https?://)?(?:www\.)?github\.com/)?zed-quill(?:/career-agent)?(?![a-z0-9@])")]


@pytest.fixture
def home(tmp_path):
    resume = {
        "contact": {
            "name": "Zephyrine Quillfeather",
            "email": "zephyrine.quill@mailbox.invalid.org",
            "phone": "+44 7700 900123",
            "github": "https://github.com/zed-quill",
        },
        "experience": [{"company": "Brightwater Analytics", "bullets": ["Rebuilt the nightly ledger import so finance closed the books two days earlier each month"]}],
        "education": [{"institution": "Northvale Polytechnic"}],
        "projects": [{"name": "LanternDB", "link": "https://lanterndb.invalid.org"}],
    }
    db = sqlite3.connect(tmp_path / "career_agent.db")
    db.execute("CREATE TABLE resumes (id INTEGER PRIMARY KEY, parsed TEXT, raw_text TEXT)")
    db.execute("CREATE TABLE email_candidates (id INTEGER PRIMARY KEY, email TEXT)")
    db.execute("INSERT INTO resumes VALUES (1, ?, ?)", (json.dumps(resume), "Zephyrine Quillfeather +44 7700 900123"))
    db.execute("INSERT INTO email_candidates VALUES (1, 'recruiter.rowan@hiringco.invalid.org'), (2, 'found@acme.com')")
    db.commit()
    db.close()
    (tmp_path / ".env").write_text("CAREER_LLM__GEMINI_API_KEY=fake-key-0123456789\nCAREER_SMTP__USERNAME=\n")
    return tmp_path


def _hits(home, text):
    return check.scan_text(text, check.build_deny_list(home), PUBLIC)


@pytest.mark.parametrize(
    "line",
    [
        'name = "Zephyrine Quillfeather"',
        'first = "zephyrine"',
        'phone = "(770) 090-0123"',  # same number, different format
        'email = "ZEPHYRINE.QUILL@MAILBOX.INVALID.ORG"',
        'company = "Brightwater Analytics"',
        'school = "Northvale Polytechnic"',
        'project = "LanternDB"',
        'bullet = "rebuilt the nightly ledger import so finance closed the books"',  # copied resume text
        'to = "recruiter.rowan@hiringco.invalid.org"',  # someone else's stored address
        'key = "fake-key-0123456789"',  # a secret from .env
    ],
)
def test_your_own_details_are_blocked(home, line):
    assert _hits(home, line), line


@pytest.mark.parametrize(
    "line",
    [
        'contact = {"name": "Jane Doe", "phone": "+1 555 010 0199", "email": "jane@example.com"}',
        'company = "Acme Corp"',
        'email = "found@acme.com"',  # placeholder domains are always fine
        "Clone https://github.com/zed-quill/career-agent to start.",  # the repo's own public URL
        "Rebuilt the import job so the team shipped on time.",  # a few shared words aren't copying
    ],
)
def test_made_up_data_and_the_public_repo_url_pass(home, line):
    assert not _hits(home, line), line


def test_private_patterns_and_allow_list(home):
    (home / "private-patterns.txt").write_text("Kestrel Rowing Club\nre:GPA\\s*9\\.\\d\n")
    (home / "private-allow.txt").write_text("LanternDB\n")
    assert _hits(home, "Captain, Kestrel Rowing Club")
    assert _hits(home, "GPA 9.12")
    assert not _hits(home, 'project = "LanternDB"')


def test_data_files_are_blocked_by_type():
    for path in ["backend/career_agent.db", "career_agent.db-wal", "x/llm_cache.sqlite", "backend/.env", "data/uploads/resume_1.pdf", "out/resume.docx", "backups/b.zip"]:
        assert check._blocked_file(path), path
    for path in ["backend/.env.example", "backend/app/config.py", "frontend/src/App.tsx"]:
        assert not check._blocked_file(path), path


def test_without_a_home_only_file_types_are_checked(tmp_path):
    deny = check.build_deny_list(tmp_path / "missing")
    assert deny.empty()
    assert check.scan_text('name = "Anyone"', deny, []) == []
