"""Company career boards on Greenhouse, Lever and Ashby (real, keyless).

Many tech companies publish every opening through their applicant-tracking
system's public job-board API: full descriptions, exact locations and a direct
apply link, straight from the company rather than an aggregator.

  greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs
  lever:      https://api.lever.co/v0/postings/{company}?mode=json
  ashby:      https://api.ashbyhq.com/posting-api/job-board/{org}

Boards come from CAREER_SCRAPER__COMPANY_BOARDS as "provider:token" entries,
optionally "provider:token=Display Name". Big boards list hundreds of roles, so
listings are filtered to tech roles (and the query/location) before any detail
request, and results are interleaved across companies for variety.
"""

from __future__ import annotations

import html
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ...config import get_settings
from ...logging_setup import get_logger
from .base import JobRecord
from .classify import (
    clean_html,
    infer_experience,
    infer_role_category,
    is_tech_role,
    normalize_job_type,
)
from .http import get_json

log = get_logger(__name__)

_GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_LEVER = "https://api.lever.co/v0/postings/{token}"
_ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{token}"


@dataclass(frozen=True)
class Board:
    provider: str
    token: str
    name: str

    @classmethod
    def parse(cls, spec: str) -> Board | None:
        provider, sep, rest = spec.strip().partition(":")
        token, _, name = rest.partition("=")
        if not sep or provider.lower() not in ("greenhouse", "lever", "ashby") or not token:
            return None
        return cls(provider.lower(), token.strip(), name.strip() or token.strip().replace("-", " ").title())


@dataclass
class _Listing:
    board: Board
    id: str
    title: str
    location: str
    url: str | None
    department: str = ""
    commitment: str | None = None
    description: str | None = None  # Lever/Ashby include it; Greenhouse needs a detail call
    posted: str = ""  # sortable timestamp (ISO string or epoch ms as zero-padded text)


# Board listings are large (hundreds of roles) and change slowly: cache them briefly.
_LIST_TTL_SECONDS = 15 * 60
_list_cache: dict[Board, tuple[float, list[_Listing]]] = {}
_cache_lock = threading.Lock()


def _list_board_cached(board: Board) -> list[_Listing]:
    with _cache_lock:
        hit = _list_cache.get(board)
    if hit and time.monotonic() - hit[0] < _LIST_TTL_SECONDS:
        return [_Listing(**vars(x)) for x in hit[1]]  # copies: callers fill descriptions
    listings = _list_board(board)
    with _cache_lock:
        _list_cache[board] = (time.monotonic(), listings)
    return [_Listing(**vars(x)) for x in listings]


def _list_board(board: Board) -> list[_Listing]:
    if board.provider == "greenhouse":
        data = get_json(_GREENHOUSE.format(token=board.token))
        return [
            _Listing(
                board,
                str(j.get("id")),
                j.get("title") or "",
                (j.get("location") or {}).get("name") or "",
                j.get("absolute_url"),
                department=" ".join(d.get("name", "") for d in j.get("departments") or []),
                posted=j.get("updated_at") or "",
            )
            for j in (data.get("jobs") or [] if isinstance(data, dict) else [])
        ]
    if board.provider == "lever":
        data = get_json(_LEVER.format(token=board.token), params={"mode": "json"})
        out = []
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            desc = "\n\n".join(
                filter(None, [j.get("descriptionPlain"), *(
                    f"{lst.get('text', '')}\n{clean_html(lst.get('content'), limit=2000)}"
                    for lst in j.get("lists") or []
                ), j.get("additionalPlain")])
            )
            out.append(
                _Listing(
                    board,
                    str(j.get("id")),
                    j.get("text") or "",
                    cats.get("location") or j.get("workplaceType") or "",
                    j.get("hostedUrl"),
                    department=f"{cats.get('department') or ''} {cats.get('team') or ''}",
                    commitment=cats.get("commitment"),
                    description=desc,
                    posted=f"{j.get('createdAt') or 0:015d}",
                )
            )
        return out
    data = get_json(_ASHBY.format(token=board.token))
    out = []
    for j in (data.get("jobs") or [] if isinstance(data, dict) else []):
        loc = j.get("location") or ""
        if j.get("isRemote") and "remote" not in loc.lower():
            loc = f"{loc} (Remote)" if loc else "Remote"
        out.append(
            _Listing(
                board,
                str(j.get("id")),
                j.get("title") or "",
                loc,
                j.get("jobUrl"),
                department=f"{j.get('department') or ''} {j.get('team') or ''}",
                commitment=j.get("employmentType"),
                description=j.get("descriptionPlain"),
                posted=j.get("publishedAt") or "",
            )
        )
    return out


def _greenhouse_description(listing: _Listing) -> str:
    try:
        data = get_json(f"{_GREENHOUSE.format(token=listing.board.token)}/{listing.id}")
    except RuntimeError:
        return ""
    # Greenhouse returns the description as entity-escaped HTML.
    return clean_html(html.unescape(data.get("content") or ""), limit=4000)


def _interleave(groups: list[list[_Listing]], limit: int) -> list[_Listing]:
    """Round-robin across companies so one huge board can't crowd out the rest.

    Each round takes every company's next-newest role, newest first, so a small
    limit still spans providers rather than whichever boards are listed first.
    """
    out: list[_Listing] = []
    i = 0
    while len(out) < limit and any(i < len(g) for g in groups):
        out.extend(sorted((g[i] for g in groups if i < len(g)), key=lambda x: x.posted, reverse=True))
        i += 1
    return out[:limit]


class CompanyBoardsSource:
    name = "companies"

    def __init__(self, boards: list[str] | None = None) -> None:
        self._specs = boards

    def boards(self) -> list[Board]:
        specs = self._specs if self._specs is not None else get_settings().scraper.company_boards
        return [b for b in (Board.parse(s) for s in specs) if b]

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        boards = self.boards()
        if not boards:
            raise RuntimeError("No company boards configured (CAREER_SCRAPER__COMPANY_BOARDS).")

        def safe_list(board: Board) -> list[_Listing]:
            try:
                return _list_board_cached(board)
            except RuntimeError as exc:
                log.warning("company board %s:%s failed: %s", board.provider, board.token, exc)
                return []

        with ThreadPoolExecutor(max_workers=8) as pool:
            per_board = list(pool.map(safe_list, boards))

        q, loc = (query or "").lower(), (location or "").lower()

        def wanted(item: _Listing) -> bool:
            haystack = f"{item.title} {item.department} {item.description or ''}".lower()
            return (
                is_tech_role(item.title)
                and (not q or q in haystack)
                and (not loc or loc in item.location.lower())
            )

        # Newest first within each company (Greenhouse lists alphabetically).
        groups = [sorted((x for x in g if wanted(x)), key=lambda x: x.posted, reverse=True) for g in per_board]
        picked = _interleave(groups, limit)
        if not picked and not any(per_board):
            raise RuntimeError("All company boards failed to respond.")

        need_detail = [x for x in picked if x.description is None]
        with ThreadPoolExecutor(max_workers=8) as pool:
            for item, desc in zip(need_detail, pool.map(_greenhouse_description, need_detail), strict=True):
                item.description = desc

        records = []
        for x in picked:
            description = clean_html(x.description, limit=4000)
            records.append(
                JobRecord(
                    source=x.board.provider,
                    external_id=f"{x.board.token}:{x.id}",
                    title=x.title,
                    company=x.board.name,
                    location=x.location or None,
                    job_type=normalize_job_type(x.commitment, title=x.title, description=description),
                    experience=infer_experience(x.title, description),
                    role_category=infer_role_category(x.title, None, description),
                    description=description,
                    url=x.url,
                    extra={"board": f"{x.board.provider}:{x.board.token}", "department": x.department.strip()},
                )
            )
        return records
