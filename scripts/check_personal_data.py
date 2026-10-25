#!/usr/bin/env python3
"""Refuse to commit personal data: data files, or anything that matches your own details.

Two checks, on staged files (the pre-commit hook) or on every tracked file (--all):

1. File types that only ever hold personal data (databases, .env, resumes as
   PDF/DOCX, backup zips) may not be committed at all.
2. File contents may not contain your personal details. The deny-list is built
   in memory, at check time, from your own Career Agent home (CAREER_HOME,
   default ~/.career-agent): the contact details, employers, schools, project
   names and sentences of every resume you uploaded, every email address the
   app has stored, and the secret values in your .env. Nothing of it is ever
   written to disk or to the repository, so the list itself cannot leak.

Test and example data must be made up; this check covers tests too.

Extra terms to block, one per line (prefix "re:" for a regex):  <home>/private-patterns.txt
Terms that are fine to commit (e.g. a common word):              <home>/private-allow.txt

Standard library only, so the git hook runs without the app's virtualenv.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BLOCKED_FILES = [
    "*.db", "*.db-*", "*.sqlite", "*.sqlite-*", "*.sqlite3",
    ".env", ".env.*",
    "*.pdf", "*.docx", "*.doc", "*.zip",
]
ALLOWED_FILES = [".env.example"]

SHINGLE_WORDS = 8  # a staged line sharing this many consecutive words with a resume is copied text
MIN_TERM = 4
_SECRET_KEY = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|USERNAME|FROM_NAME|EMAIL)$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
# Made-up addresses are what tests and examples should use; never block them.
_PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net", "acme.com", ".test", ".invalid", "localhost")


@dataclass(frozen=True)
class Term:
    text: str  # lowercased
    kind: str


def career_home() -> Path:
    return Path(os.environ.get("CAREER_HOME") or Path.home() / ".career-agent").expanduser()


def _env_values(home: Path) -> dict[str, str]:
    env = home / ".env"
    values: dict[str, str] = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    return values


def _database(home: Path, env: dict[str, str]) -> Path | None:
    url = os.environ.get("CAREER_DB_URL") or env.get("CAREER_DB_URL") or ""
    path = Path(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else home / "career_agent.db"
    return path if path.exists() else None


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _shingles(text: str) -> set[tuple[str, ...]]:
    w = _words(text)
    return {tuple(w[i : i + SHINGLE_WORDS]) for i in range(len(w) - SHINGLE_WORDS + 1)}


def _link_terms(url: str | None) -> list[str]:
    if not url:
        return []
    bare = re.sub(r"^(https?://)?(www\.)?", "", url.strip().lower()).rstrip("/")
    handle = bare.rsplit("/", 1)[-1]
    return [bare, handle] if "/" in bare else [bare]


class DenyList:
    def __init__(self) -> None:
        self.terms: dict[str, Term] = {}
        self.phones: set[str] = set()  # last 10 digits
        self.shingles: set[tuple[str, ...]] = set()
        self.regexes: list[tuple[re.Pattern[str], str]] = []

    def add(self, text: str | None, kind: str) -> None:
        text = (text or "").strip().lower()
        if "@" in text and text.endswith(_PLACEHOLDER_DOMAINS):
            return
        if len(text) >= MIN_TERM and text not in self.terms:
            self.terms[text] = Term(text, kind)

    def add_phone(self, text: str | None) -> None:
        digits = _digits(text or "")
        if len(digits) >= 10:
            self.phones.add(digits[-10:])

    def empty(self) -> bool:
        return not (self.terms or self.phones or self.shingles or self.regexes)


def _add_resume(deny: DenyList, data: dict) -> None:
    contact = data.get("contact") or {}
    deny.add(contact.get("name"), "name")
    for part in (contact.get("name") or "").split():
        deny.add(part, "name")
    email = contact.get("email")
    deny.add(email, "email")
    deny.add_phone(contact.get("phone"))
    for link in ("linkedin", "github", "website"):
        for term in _link_terms(contact.get(link)):
            deny.add(term, "profile link")
    for item in data.get("experience") or []:
        deny.add(item.get("company"), "employer")
    for item in data.get("education") or []:
        deny.add(item.get("institution"), "school")
    for item in data.get("projects") or []:
        deny.add(item.get("name"), "project name")
        for term in _link_terms(item.get("link")):
            deny.add(term, "project link")
    texts = [data.get("summary") or ""]
    for section in ("experience", "projects"):
        for item in data.get(section) or []:
            texts.extend(item.get("bullets") or [])
    for section in data.get("extra_sections") or []:
        texts.extend(section.get("items") or [])
    for text in texts:
        deny.shingles |= _shingles(text)


def build_deny_list(home: Path) -> DenyList:
    deny = DenyList()
    env = _env_values(home)
    for key, value in env.items():
        if key.startswith("CAREER_") and _SECRET_KEY.search(key) and len(value) >= 6:
            deny.add(value, "value from your .env")
    db_path = _database(home, env)
    if db_path:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            if "resumes" in tables:
                for parsed, raw in conn.execute("SELECT parsed, raw_text FROM resumes"):
                    try:
                        _add_resume(deny, json.loads(parsed) if isinstance(parsed, str) else parsed or {})
                    except (ValueError, AttributeError):
                        pass
                    deny.shingles |= _shingles(raw or "")
                    for phone in _PHONE.findall(raw or ""):
                        deny.add_phone(phone)
            # Every email address anywhere: yours, recruiters', contacts'.
            for table in tables:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
                for col in cols:
                    for (value,) in conn.execute(f'SELECT "{col}" FROM "{table}" WHERE typeof("{col}") = \'text\''):
                        for email in _EMAIL.findall(value):
                            deny.add(email, "stored email address")
        finally:
            conn.close()
    extra = home / "private-patterns.txt"
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("re:"):
                deny.regexes.append((re.compile(line[3:], re.IGNORECASE), "private pattern"))
            elif line and not line.startswith("#"):
                deny.add(line, "private pattern")
    allow = home / "private-allow.txt"
    if allow.exists():
        for line in allow.read_text(encoding="utf-8").splitlines():
            deny.terms.pop(line.strip().lower(), None)
    return deny


def _public_identity() -> list[re.Pattern[str]]:
    """The repository's own GitHub owner/name is public; a match inside a reference to it is fine."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$", url)
    if not m:
        return []
    owner, repo = re.escape(m.group(1).lower()), re.escape(m.group(2).lower())
    return [re.compile(rf"(?<![a-z0-9.@])(?:(?:https?://)?(?:www\.)?github\.com/)?{owner}(?:/{repo})?(?![a-z0-9@])")]


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def _files(staged: bool) -> list[str]:
    out = _git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR") if staged else _git("ls-files", "-z")
    return [p for p in out.decode().split("\0") if p]


def _blocked_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in ALLOWED_FILES:
        return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in BLOCKED_FILES)


def _mask(text: str) -> str:
    return text if len(text) <= 2 else f"{text[0]}{'*' * (len(text) - 2)}{text[-1]}"


def scan_text(text: str, deny: DenyList, public: list[re.Pattern[str]]) -> list[tuple[int, str]]:
    """(line number, reason) for every line that matches the deny-list."""
    if deny.empty():
        return []
    terms = sorted(deny.terms.values(), key=lambda t: -len(t.text))
    pattern = (
        re.compile("|".join(rf"(?<![a-z0-9]){re.escape(t.text)}(?![a-z0-9])" for t in terms)) if terms else None
    )
    hits: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        public_spans = [m.span() for p in public for m in p.finditer(low)]
        found = next(
            (
                m
                for m in (pattern.finditer(low) if pattern else ())
                if not any(start <= m.start() and m.end() <= end for start, end in public_spans)
            ),
            None,
        )
        reason = None
        if found:
            reason = f"matches your {deny.terms[found.group(0)].kind} ({_mask(found.group(0))})"
        elif deny.phones and any(_digits(p)[-10:] in deny.phones for p in _PHONE.findall(low)):
            reason = "matches your phone number"
        elif deny.shingles and _shingles(low) & deny.shingles:
            reason = f"copies {SHINGLE_WORDS}+ words of your resume text"
        else:
            for rx, kind in deny.regexes:
                if rx.search(line):
                    reason = f"matches a {kind}"
                    break
        if reason:
            hits.append((number, reason))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="check staged files (default; used by the git hook)")
    mode.add_argument("--all", action="store_true", help="check every tracked file")
    args = parser.parse_args(argv)

    home = career_home()
    deny = build_deny_list(home)
    public = _public_identity()
    problems: list[str] = []
    for path in _files(staged=not args.all):
        if _blocked_file(path):
            problems.append(f"{path}: this kind of file holds personal data and must not be committed")
            continue
        for _, reason in scan_text(path, deny, public):
            problems.append(f"{path}: the file name {reason}")
        blob = _git("show", f":{path}")
        if len(blob) > 5_000_000:
            continue
        for number, reason in scan_text(blob.decode("utf-8", errors="ignore"), deny, public):
            problems.append(f"{path}:{number}: {reason}")

    if deny.empty():
        print(f"personal-data check: no Career Agent data in {home}; checked file types only", file=sys.stderr)
    if problems:
        print("Personal data found. Nothing was committed:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            "\nUse made-up data instead (names, numbers, companies, schools, sentences).\n"
            f"If a match is a false alarm, add the term to {home / 'private-allow.txt'}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
