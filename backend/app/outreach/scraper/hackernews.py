"""Hacker News "Ask HN: Who is hiring?" source (real, keyless).

Y Combinator posts a monthly "Who is hiring?" thread under the `whoishiring`
account; each top-level comment is an individual job post (many from YC
companies, and a good number include a direct recruiter email). We use the free
HN Algolia API to find the latest thread and read its comments.

  search:  https://hn.algolia.com/api/v1/search_by_date
  item:    https://hn.algolia.com/api/v1/items/{id}
"""

from __future__ import annotations

import re

from ..email_finder.base import EMAIL_RE
from .base import JobRecord
from .classify import clean_html, infer_experience, infer_role_category, normalize_job_type
from .http import get_json

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"

_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
# "|" splits anywhere; dashes/bullets only when spaced, so "full-time" stays whole.
_PIPE_SPLIT = re.compile(r"\s*\|\s*|\s+[•·–—-]{1,3}\s+")


def _latest_thread_id() -> int | None:
    data = get_json(
        SEARCH_URL,
        params={"tags": "story,author_whoishiring", "query": "hiring", "hitsPerPage": 20},
    )
    hits = data.get("hits", []) if isinstance(data, dict) else []
    for hit in hits:
        title = (hit.get("title") or "").lower()
        # Match the hiring thread, not "freelancer?" or "who wants to be hired?".
        if "who is hiring" in title:
            oid = hit.get("objectID")
            if oid:
                return int(oid)
    return None


_GREETING_RE = re.compile(r"^(hey\s+hn[!,. ]*|hn[:!]\s*|hello[!,. ]*)", re.IGNORECASE)


def _parse_company_title(first_line: str) -> tuple[str, str]:
    segments = [s.strip() for s in _PIPE_SPLIT.split(first_line) if s.strip()]
    if not segments:
        return "", ""
    company = _GREETING_RE.sub("", segments[0]).strip()
    # Drop "(https://...)" / "[YC W21]" annotations and bare URLs after the name.
    company = re.split(r"\s*[(\[]|\s+https?://", company)[0].strip()[:120]
    title = ""
    # The role usually sits in one of the next couple of segments.
    role_hint = re.compile(
        r"\b(engineer|developer|scientist|manager|designer|devops|sre|lead|architect|"
        r"analyst|fullstack|full.stack|frontend|backend|ml|ai|data)",
        re.IGNORECASE,
    )
    for seg in segments[1:5]:
        if role_hint.search(seg):
            title = seg[:160]
            break
    # No recognizable role segment: a generic title beats "150 employees" or "Remote".
    return company, title or "Engineering role"


class HackerNewsSource:
    name = "hackernews"

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        thread_id = _latest_thread_id()
        if thread_id is None:
            return []

        item = get_json(ITEM_URL.format(id=thread_id))
        children = item.get("children", []) if isinstance(item, dict) else []

        q = (query or "").lower()
        loc = (location or "").lower()
        records: list[JobRecord] = []
        for child in children:
            raw = child.get("text") or ""
            if not raw or child.get("author") == "whoishiring":
                continue
            text = clean_html(raw, limit=4000)
            if not text:
                continue
            # The header ("Company | Role | Location | ...") is the first paragraph.
            header = text.split("\n")[0]

            blob = text.lower()
            if q and q not in blob:
                continue
            if loc and loc not in blob:
                continue

            company, title = _parse_company_title(header)
            if not company:
                continue

            # Real recruiter contact: an email and/or an apply link from the post.
            email_match = EMAIL_RE.search(text)
            apply_url = None
            href = _HREF_RE.search(raw)
            if href:
                apply_url = href.group(1)

            is_remote = "remote" in blob
            records.append(
                JobRecord(
                    source="hackernews",
                    external_id=str(child.get("id")),
                    title=title,
                    company=company,
                    location="Remote" if is_remote else (location or "See post"),
                    job_type=normalize_job_type(None, title=title, description=text),
                    experience=infer_experience(title, text),
                    role_category=infer_role_category(title, None, text),
                    description=text[:1500],
                    url=apply_url or f"https://news.ycombinator.com/item?id={child.get('id')}",
                    recruiter_email=email_match.group(0).lower() if email_match else None,
                    extra={"hn_thread": thread_id},
                )
            )
            if len(records) >= limit:
                break
        return records
