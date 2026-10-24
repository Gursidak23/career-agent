import pytest

from app.outreach.email_finder.base import (
    GRADE_MX_ONLY,
    GRADE_UNVERIFIED,
    GRADE_VERIFIED,
    EmailCandidate,
)
from app.outreach.email_finder.domain import (
    candidate_domains,
    domain_from_url,
    resolve_domain,
    slug_from_company,
)
from app.outreach.email_finder.patterns import PatternFinder, generate_emails
from app.outreach.email_finder.service import EmailFinderService


# --------------------------------------------------------------------------- #
# domain resolution
# --------------------------------------------------------------------------- #
def test_slug_strips_punctuation_and_spaces():
    assert slug_from_company("Acme, Inc.") == "acmeinc"
    assert slug_from_company("Foo-Bar Labs") == "foobarlabs"


def test_domain_from_url_ignores_job_boards():
    assert domain_from_url("https://www.linkedin.com/jobs/view/123") is None
    assert domain_from_url("https://boards.greenhouse.io/acme/jobs/1") is None


def test_domain_from_url_extracts_company_host():
    assert domain_from_url("https://careers.acme.com/job/42") == "careers.acme.com"
    assert domain_from_url("http://www.acme.io/about") == "acme.io"


def test_candidate_domains_guesses_tlds():
    doms = candidate_domains("Acme")
    assert "acme.com" in doms and "acme.io" in doms


def test_resolve_prefers_explicit_then_url():
    assert resolve_domain("Acme", "acme.com", "https://x.io") == "acme.com"
    assert resolve_domain("Acme", None, "https://careers.acme.io/1") == "careers.acme.io"
    # No known domain -> None (guessing is left to candidate_domains).
    assert resolve_domain("Acme", None, None) is None


# --------------------------------------------------------------------------- #
# pattern generation
# --------------------------------------------------------------------------- #
def test_generate_emails_common_formats():
    emails = dict(generate_emails("Jane Doe", "acme.com"))
    assert "jane.doe@acme.com" in emails
    assert "janedoe@acme.com" in emails
    assert "jdoe@acme.com" in emails


def test_generate_emails_single_name_skips_last_templates():
    emails = dict(generate_emails("Cher", "acme.com"))
    assert "cher@acme.com" in emails
    assert all("@acme.com" in e for e in emails)


@pytest.mark.asyncio
async def test_pattern_finder_needs_name():
    finder = PatternFinder()
    assert await finder.find(name=None, company="Acme", domain="acme.com", job_url=None) == []


@pytest.mark.asyncio
async def test_pattern_finder_discounts_guessed_domains():
    finder = PatternFinder()
    with_domain = await finder.find(name="Jane Doe", company="Acme", domain="acme.com", job_url=None)
    guessed = await finder.find(name="Jane Doe", company="Acme", domain=None, job_url=None)
    top_known = max(c.confidence for c in with_domain)
    top_guess = max(c.confidence for c in guessed)
    assert top_guess < top_known


# --------------------------------------------------------------------------- #
# candidate ranking
# --------------------------------------------------------------------------- #
def test_sort_key_prioritizes_verification_then_confidence():
    verified = EmailCandidate("a@x.com", "pattern", 0.1, GRADE_VERIFIED)
    mx = EmailCandidate("b@x.com", "pattern", 0.9, GRADE_MX_ONLY)
    unv = EmailCandidate("c@x.com", "pattern", 0.95, GRADE_UNVERIFIED)
    ranked = sorted([unv, mx, verified], key=lambda c: c.sort_key(), reverse=True)
    assert [c.email for c in ranked] == ["a@x.com", "b@x.com", "c@x.com"]


# --------------------------------------------------------------------------- #
# service orchestration (mocked providers + verification)
# --------------------------------------------------------------------------- #
class _StubFinder:
    def __init__(self, name, candidates):
        self.name = name
        self._candidates = candidates

    async def find(self, *, name, company, domain, job_url):
        return list(self._candidates)


@pytest.mark.asyncio
async def test_service_merges_dedupes_and_ranks(monkeypatch):
    service = EmailFinderService()

    stub1 = _StubFinder("a", [EmailCandidate("dup@x.com", "crawler", 0.5)])
    stub2 = _StubFinder(
        "b",
        [
            EmailCandidate("dup@x.com", "pattern", 0.9),  # higher confidence dup
            EmailCandidate("new@x.com", "pattern", 0.6),
        ],
    )
    monkeypatch.setattr(service, "_chain", lambda: [stub1, stub2])

    # No verified hit -> chain runs fully so we can observe the merge.
    async def fake_verify(email):
        return GRADE_MX_ONLY

    monkeypatch.setattr("app.outreach.email_finder.service.verify_email", fake_verify)

    results = await service.find(company="Acme")
    emails = [c.email for c in results]
    # De-duped to two; higher-confidence dup ranked first.
    assert emails == ["dup@x.com", "new@x.com"]
    assert results[0].confidence == 0.9  # kept the stronger confidence
    assert results[0].verified == GRADE_MX_ONLY


@pytest.mark.asyncio
async def test_service_short_circuits_on_verified(monkeypatch):
    service = EmailFinderService()
    calls = {"n": 0}

    class _Counting(_StubFinder):
        async def find(self, *, name, company, domain, job_url):
            calls["n"] += 1
            return await super().find(name=name, company=company, domain=domain, job_url=job_url)

    first = _Counting("first", [EmailCandidate("hit@x.com", "crawler", 0.7)])
    second = _Counting("second", [EmailCandidate("other@x.com", "pattern", 0.7)])
    monkeypatch.setattr(service, "_chain", lambda: [first, second])

    async def fake_verify(email):
        return GRADE_VERIFIED

    monkeypatch.setattr("app.outreach.email_finder.service.verify_email", fake_verify)

    results = await service.find(company="Acme")
    assert calls["n"] == 1  # stopped after first provider produced a verified hit
    assert results[0].email == "hit@x.com"


# --------------------------------------------------------------------------- #
# API smoke (mocked finder + verification, no network)
# --------------------------------------------------------------------------- #
def test_email_endpoints_smoke(monkeypatch):
    from fastapi.testclient import TestClient

    import app.routers.email as email_router
    from app.main import app

    class _Svc:
        async def find(self, *, name, company, domain, job_url):
            return [EmailCandidate("found@acme.com", "crawler", 0.8, GRADE_VERIFIED, name)]

    monkeypatch.setattr(email_router, "get_service", lambda: _Svc())

    async def fake_verify(email):
        return GRADE_MX_ONLY

    monkeypatch.setattr(email_router, "verify_email", fake_verify)

    client = TestClient(app)

    res = client.post("/api/email/find", json={"company": "Acme", "name": "Jane Doe"})
    assert res.status_code == 200
    data = res.json()
    assert data["best"]["email"] == "found@acme.com"
    assert data["candidates"][0]["verified"] == GRADE_VERIFIED

    res = client.post("/api/email/verify", json={"email": "x@acme.com"})
    assert res.status_code == 200
    assert res.json()["verified"] == GRADE_MX_ONLY

    # settings status should now include email providers
    res = client.get("/api/settings/status")
    assert res.status_code == 200
    names = {p["name"] for p in res.json()["email_providers"]}
    assert {"crawler", "pattern"}.issubset(names)
