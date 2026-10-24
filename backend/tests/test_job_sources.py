from app.outreach.scraper import source_names
from app.outreach.scraper.classify import (
    clean_html,
    infer_experience,
    infer_role_category,
    normalize_job_type,
)


# --------------------------------------------------------------------------- #
# classification heuristics (pure)
# --------------------------------------------------------------------------- #
def test_infer_role_category_specific_over_generic():
    assert infer_role_category("Senior Machine Learning Engineer") == "ai_engineer"
    assert infer_role_category("Data Scientist") == "data_scientist"
    assert infer_role_category("Frontend Developer", ["react"]) == "web_developer"
    assert infer_role_category("Backend Engineer") == "backend_engineer"
    assert infer_role_category("Android Developer") == "app_developer"
    assert infer_role_category("Site Reliability Engineer") == "devops_engineer"
    # Generic developer falls back to software_developer.
    assert infer_role_category("Software Engineer") == "software_developer"
    assert infer_role_category("Project Coordinator") == "software_developer"


def test_infer_experience_levels():
    assert infer_experience("Senior Backend Engineer") == "senior"
    assert infer_experience("Principal Architect") == "lead"
    assert infer_experience("Junior Developer") == "junior"
    assert infer_experience("Engineering Intern") == "entry"
    assert infer_experience("Backend Engineer") == "mid"


def test_normalize_job_type():
    assert normalize_job_type("Full Time") == "full_time"
    assert normalize_job_type("contract") == "contract"
    assert normalize_job_type(None, title="Engineering Internship") == "internship"
    assert normalize_job_type(None) == "full_time"


def test_clean_html_strips_tags_and_entities():
    html = "<p>Hello&amp;world <b>now</b></p>"
    assert clean_html(html) == "Hello&world now"
    assert clean_html(None) == ""


# --------------------------------------------------------------------------- #
# registry no longer exposes sample; real sources registered
# --------------------------------------------------------------------------- #
def test_registry_is_real_sources_only():
    names = source_names()
    assert "sample" not in names
    for expected in ["all", "remotive", "remoteok", "arbeitnow", "hackernews"]:
        assert expected in names


# --------------------------------------------------------------------------- #
# source parsing with mocked HTTP (no network)
# --------------------------------------------------------------------------- #
def test_remotive_parses_records(monkeypatch):
    from app.outreach.scraper import remotive

    payload = {
        "jobs": [
            {
                "id": 123,
                "url": "https://remotive.com/job/123",
                "title": "Senior Backend Engineer",
                "company_name": "Acme",
                "category": "Software Development",
                "tags": ["python", "go"],
                "job_type": "full_time",
                "candidate_required_location": "Worldwide",
                "salary": "$120k",
                "description": "<p>Build <b>scalable</b> services.</p>",
            }
        ]
    }
    monkeypatch.setattr(remotive, "get_json", lambda *a, **k: payload)

    records = remotive.RemotiveSource().fetch(limit=10)
    assert len(records) == 1
    rec = records[0]
    assert rec.source == "remotive"
    assert rec.company == "Acme"
    assert rec.experience == "senior"
    assert rec.role_category == "backend_engineer"
    assert rec.job_type == "full_time"
    assert "<" not in (rec.description or "")  # HTML stripped


def test_remoteok_skips_metadata_object(monkeypatch):
    from app.outreach.scraper import remoteok

    payload = [
        {"legal": "notice"},  # leading metadata element
        {
            "id": "9",
            "position": "Machine Learning Engineer",
            "company": "DeepCo",
            "location": "Remote",
            "tags": ["ml", "python"],
            "description": "Train models.",
            "url": "https://remoteok.com/remote-jobs/9",
        },
    ]
    monkeypatch.setattr(remoteok, "get_json", lambda *a, **k: payload)

    records = remoteok.RemoteOkSource().fetch(limit=10)
    assert len(records) == 1
    assert records[0].company == "DeepCo"
    assert records[0].role_category == "ai_engineer"


def test_hackernews_parses_company_email(monkeypatch):
    from app.outreach.scraper import hackernews

    monkeypatch.setattr(hackernews, "_latest_thread_id", lambda: 42)
    item = {
        "children": [
            {
                "id": 1001,
                "author": "someuser",
                "text": (
                    "Acme Corp | Senior Backend Engineer | Remote | "
                    "Apply at <a href=\"https://acme.com/careers\">link</a> "
                    "or email jobs@acme.com"
                ),
            },
            {"id": 1002, "author": "whoishiring", "text": "meta comment"},
        ]
    }
    monkeypatch.setattr(hackernews, "get_json", lambda *a, **k: item)

    records = hackernews.HackerNewsSource().fetch(limit=10)
    assert len(records) == 1
    rec = records[0]
    assert rec.company == "Acme Corp"
    assert rec.role_category == "backend_engineer"
    assert rec.recruiter_email == "jobs@acme.com"
    assert rec.url == "https://acme.com/careers"


def test_aggregate_merges_and_dedupes(monkeypatch):
    from app.outreach.scraper import aggregate
    from app.outreach.scraper.base import JobRecord

    class _Stub:
        def __init__(self, name, recs):
            self.name = name
            self._recs = recs

        def fetch(self, *, query=None, location=None, limit=25):
            return self._recs

    dup = JobRecord(source="a", title="Engineer", company="Acme")
    src = aggregate.AggregateSource()
    src._sources = [
        _Stub("a", [dup]),
        _Stub("b", [JobRecord(source="b", title="Engineer", company="Acme")]),  # dup
        _Stub("c", [JobRecord(source="c", title="Designer", company="Beta")]),
    ]
    records = src.fetch(limit=10)
    keys = {(r.company, r.title) for r in records}
    assert keys == {("Acme", "Engineer"), ("Beta", "Designer")}


def test_apify_jobs_requires_token(monkeypatch):
    from app.outreach.scraper import apify_jobs

    monkeypatch.setattr(apify_jobs, "_resolve_token", lambda: None)
    try:
        apify_jobs.ApifyJobsSource().fetch(query="engineer", limit=5)
        assert False, "expected RuntimeError when no token"
    except RuntimeError as exc:
        assert "Apify job source not configured" in str(exc)


def test_apify_jobs_parses_items(monkeypatch):
    from app.outreach.scraper import apify_jobs

    monkeypatch.setattr(apify_jobs, "_resolve_token", lambda: "tok")
    items = [
        {
            "title": "Frontend Developer",
            "company": "Zomato",
            "location": "Bangalore",
            "link": "https://naukri.com/job/1",
            "source": "naukri",
            "keyword": "Frontend Developer",
            "datePosted": "2026-06-26",
        },
        {"title": "", "company": ""},  # skipped (no title/company)
    ]
    monkeypatch.setattr(apify_jobs, "post_json", lambda *a, **k: items)

    records = apify_jobs.ApifyJobsSource().fetch(query="frontend", location="Bangalore", limit=10)
    assert len(records) == 1
    rec = records[0]
    assert rec.source == "apify"
    assert rec.company == "Zomato"
    assert rec.role_category == "web_developer"
    assert rec.experience == "entry"
    assert rec.url == "https://naukri.com/job/1"
    assert rec.extra["board"] == "naukri"


def test_apify_not_in_keyless_aggregator():
    # Apify costs money per run, so it must not be pulled by the keyless `all`.
    from app.outreach.scraper.aggregate import AggregateSource

    names = {s.name for s in AggregateSource()._sources}
    assert "apify" not in names


def test_aggregate_raises_only_when_all_fail(monkeypatch):
    from app.outreach.scraper import aggregate

    class _Boom:
        name = "boom"

        def fetch(self, *, query=None, location=None, limit=25):
            raise RuntimeError("down")

    src = aggregate.AggregateSource()
    src._sources = [_Boom(), _Boom()]
    try:
        src.fetch(limit=5)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "All job sources failed" in str(exc)


def test_hackernews_header_parsing_real_cases():
    from app.outreach.scraper.hackernews import _parse_company_title

    assert _parse_company_title(
        "Air Space Intelligence (https://www.airspace.com) | Software Engineer | Boston"
    ) == ("Air Space Intelligence", "Software Engineer")
    # No role segment: generic title instead of "150 employees".
    assert _parse_company_title("SmarterDx | 150 employees | Remote") == ("SmarterDx", "Engineering role")
    assert _parse_company_title("Snout https://snout.com/ | Backend Engineer")[0] == "Snout"
    # Hyphens inside words are not separators.
    assert _parse_company_title("Acme | Full-stack Engineer | full-time")[1] == "Full-stack Engineer"


def test_clean_html_decodes_all_entities_and_keeps_paragraphs():
    assert clean_html("<p>Kotlin&#x2F;Java</p><p>Remote&nbsp;only</p>") == "Kotlin/Java\n\nRemote only"
