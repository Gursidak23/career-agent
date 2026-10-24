"""Job match ranking, application tracker, per-bullet review, company boards, digest."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app import db as db_module
from app.db import Base, get_db
from app.main import app
from app.models import Application, JobPosting, Resume, Tailoring
from app.outreach import job_feed
from app.outreach.matching import match_job, resume_lower
from app.outreach.scraper import company_boards
from app.outreach.scraper.classify import is_tech_role
from app.routers import outreach as outreach_router
from app.schemas import (
    BulletReview,
    ContactInfo,
    ExperienceItem,
    ResumeData,
    SendResult,
)

RESUME = ResumeData(
    contact=ContactInfo(name="Jane Doe", email="jane@example.com"),
    skills=["Python", "FastAPI", "PostgreSQL", "Docker", "SQL", "REST API"],
    experience=[
        ExperienceItem(
            title="Engineer",
            company="Acme",
            bullets=["Built FastAPI services on PostgreSQL, cutting latency by 40%.", "Ran CI on Docker."],
        )
    ],
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    # Background sends open their own session.
    monkeypatch.setattr(outreach_router, "SessionLocal", factory)
    try:
        yield TestClient(app), factory
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed(factory):
    s = factory()
    resume = Resume(raw_text="x", parsed=RESUME.model_dump())
    good = JobPosting(
        source="t", title="Backend Engineer", company="Globex",
        description="We use Python, SQL, REST API design and PostgreSQL on Docker.", role_category="backend_engineer",
    )
    poor = JobPosting(
        source="t", title="iOS Engineer", company="Initech",
        description="Swift, SwiftUI, Xcode, iOS and Kotlin Multiplatform.", role_category="app_developer",
    )
    s.add_all([resume, good, poor])
    s.commit()
    return resume.id, good.id, poor.id


# ---------------------------------------------------------------- migration --
def test_auto_migration_adds_new_nullable_columns(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # an "old" tailorings table without the new columns
        conn.execute(text("CREATE TABLE tailorings (id INTEGER PRIMARY KEY, resume_id INTEGER, role VARCHAR(128))"))
        conn.execute(text("INSERT INTO tailorings (id, resume_id, role) VALUES (1, 1, 'x')"))
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.init_db()
    cols = {c["name"] for c in inspect(engine).get_columns("tailorings")}
    assert {"reviews", "job_id", "ats_score"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT role FROM tailorings WHERE id=1")).scalar() == "x"


# ------------------------------------------------------------------ matching --
def test_match_scores_rank_fitting_jobs_higher():
    text_ = resume_lower(RESUME)
    good = match_job(text_, "Backend Engineer", "Python, SQL, REST API, PostgreSQL and Docker.", "backend_engineer")
    poor = match_job(text_, "iOS Engineer", "Swift, SwiftUI, Xcode, iOS and Kotlin.", "app_developer")
    assert good.score > 70 and poor.score < 30
    assert "PostgreSQL" in good.matched and "Swift" in poor.missing
    # A post naming only two skills says little: both matched still scores 40.
    assert match_job(text_, "Engineer", "Python and Docker.", None).score == 40
    assert match_job(text_, "Sales Manager", "Grow revenue.", None).score == 0
    # "golang" counts as Go, which this resume lacks.
    assert "Go" in match_job(text_, "Backend Engineer (Golang)", "Golang, Python, SQL, Docker, PostgreSQL", None).missing


def test_jobs_api_sorts_by_match_and_shows_tracker_status(env):
    client, factory = env
    resume_id, good_id, poor_id = _seed(factory)
    client.post("/api/applications", json={"job_id": poor_id})
    rows = client.get(f"/api/jobs?resume_id={resume_id}&sort=match").json()
    assert [r["id"] for r in rows] == [good_id, poor_id]
    assert rows[0]["match_score"] > rows[1]["match_score"]
    assert rows[1]["application_status"] == "saved" and rows[0]["application_status"] is None
    assert [r["id"] for r in client.get(f"/api/jobs?resume_id={resume_id}&min_match=50").json()] == [good_id]


# ------------------------------------------------------------------- tracker --
def test_tracker_create_is_idempotent_and_status_stamps_dates(env):
    client, factory = env
    _, good_id, _ = _seed(factory)
    a = client.post("/api/applications", json={"job_id": good_id}).json()
    again = client.post("/api/applications", json={"job_id": good_id}).json()
    assert a["id"] == again["id"] and a["company"] == "Globex" and a["status"] == "saved"
    applied = client.patch(f"/api/applications/{a['id']}", json={"status": "applied", "notes": "Referral"}).json()
    assert applied["applied_at"] and applied["notes"] == "Referral"
    manual = client.post("/api/applications", json={"company": "Hooli", "role": "SRE"}).json()
    assert len(client.get("/api/applications").json()) == 2
    assert client.delete(f"/api/applications/{manual['id']}").json() == {"ok": True}
    assert client.post("/api/applications", json={}).status_code == 422


def test_send_skips_repeats_and_marks_card_contacted(env, monkeypatch):
    client, factory = env
    _, good_id, _ = _seed(factory)

    async def fake_send(items, **kwargs):
        return [SendResult(to_email=str(i.to_email), status="sent") for i in items]

    monkeypatch.setattr(outreach_router, "send_batch", fake_send)
    monkeypatch.setattr(outreach_router, "smtp_configured", lambda: True)
    item = {"to_email": "hr@globex.com", "subject": "Hi", "body": "Hello", "company": "Globex",
            "role": "Backend Engineer", "job_id": good_id}

    first = client.post("/api/outreach/send", json={"items": [item]}).json()
    assert first["queued"] == 1
    card = client.get("/api/applications").json()[0]
    assert card["status"] == "contacted" and card["recruiter_email"] == "hr@globex.com"
    assert card["emails_sent"] == 1 and card["contacted_at"]

    again = client.post("/api/outreach/send", json={"items": [item]}).json()
    assert again["queued"] == 0 and again["results"][0]["status"] == "skipped"
    assert client.get("/api/outreach/contacted?email=HR@globex.com").json()["count"] == 1
    forced = client.post("/api/outreach/send", json={"items": [item], "allow_repeat": True}).json()
    assert forced["queued"] == 1


def test_contacted_never_moves_a_card_backwards(env, monkeypatch):
    client, factory = env
    _, good_id, _ = _seed(factory)
    a = client.post("/api/applications", json={"job_id": good_id, "status": "interview"}).json()

    async def fake_send(items, **kwargs):
        return [SendResult(to_email=str(i.to_email), status="sent") for i in items]

    monkeypatch.setattr(outreach_router, "send_batch", fake_send)
    monkeypatch.setattr(outreach_router, "smtp_configured", lambda: True)
    client.post("/api/outreach/send", json={"items": [
        {"to_email": "hr@globex.com", "subject": "s", "body": "b", "job_id": good_id}]})
    assert client.get("/api/applications").json()[0]["status"] == "interview"
    assert a["id"]


# -------------------------------------------------------------------- review --
def test_review_endpoint_applies_choices_and_rescores(env):
    client, factory = env
    resume_id, _, _ = _seed(factory)
    s = factory()
    held = BulletReview(section="experience", entry=0, index=1, label="Acme",
                        original="Ran CI on Docker.", suggested="Ran CI on Docker and Kubernetes.",
                        flags=["Adds Kubernetes, not in your original"], applied=False)
    t = Tailoring(resume_id=resume_id, role="devops_engineer", tailored=RESUME.model_dump(),
                  reviews=[held.model_dump()])
    s.add(t)
    s.commit()

    before = client.get(f"/api/resume/tailorings/{t.id}").json()
    assert before["reviews"][0]["applied"] is False
    after = client.post(f"/api/resume/tailorings/{t.id}/review", json={"applied": [True]}).json()
    assert after["tailored"]["experience"][0]["bullets"][1] == "Ran CI on Docker and Kubernetes."
    assert after["reviews"][0]["applied"] is True
    assert after["ats"]["score"] >= before["ats"]["score"]
    assert client.post(f"/api/resume/tailorings/{t.id}/review", json={"applied": []}).status_code == 422


# ------------------------------------------------------------ company boards --
def test_company_boards_filter_interleave_and_fill_descriptions(monkeypatch):
    calls = []

    def fake_get_json(url, params=None, timeout=25.0):
        calls.append(url)
        if "greenhouse" in url and url.endswith("/jobs"):
            return {"jobs": [
                {"id": 1, "title": "Backend Engineer", "location": {"name": "Bengaluru, India"},
                 "absolute_url": "https://gh/1", "updated_at": "2026-10-01"},
                {"id": 2, "title": "Account Executive", "location": {"name": "Remote"}, "updated_at": "2026-10-02"},
            ]}
        if "greenhouse" in url:
            return {"content": "&lt;p&gt;Python &amp;amp; Kafka&lt;/p&gt;"}
        if "lever" in url:
            return [{"id": "a", "text": "ML Engineer", "categories": {"location": "Remote", "commitment": "Full-time"},
                     "hostedUrl": "https://lever/a", "descriptionPlain": "PyTorch", "createdAt": 5}]
        return {"jobs": [{"id": "z", "title": "Solutions Engineer", "location": "NYC", "jobUrl": "https://ashby/z"}]}

    company_boards._list_cache.clear()
    monkeypatch.setattr(company_boards, "get_json", fake_get_json)
    src = company_boards.CompanyBoardsSource(["greenhouse:acme=Acme", "lever:beta", "ashby:gamma", "bogus"])
    recs = src.fetch(limit=10)
    assert {(r.company, r.title) for r in recs} == {("Acme", "Backend Engineer"), ("Beta", "ML Engineer")}
    gh = next(r for r in recs if r.source == "greenhouse")
    assert gh.description == "Python & Kafka" and gh.location == "Bengaluru, India"
    assert [r.title for r in src.fetch(location="india", limit=10)] == ["Backend Engineer"]


def test_is_tech_role():
    assert is_tech_role("Senior Backend Engineer") and is_tech_role("Data Analyst")
    assert not is_tech_role("Solutions Engineer") and not is_tech_role("AI Trainer")


# -------------------------------------------------------------------- digest --
@pytest.mark.asyncio
async def test_scheduled_refresh_emails_digest_of_good_matches(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'd.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    s.add(Resume(raw_text="x", parsed=RESUME.model_dump()))
    s.commit()

    from app.outreach.scraper.base import JobRecord

    class FakeSource:
        def fetch(self, **kw):
            return [
                JobRecord(source="t", external_id="1", title="Backend Engineer", company="Globex",
                          description="Python, FastAPI, PostgreSQL, Docker"),
                JobRecord(source="t", external_id="2", title="iOS Engineer", company="Initech",
                          description="Swift, SwiftUI, Xcode, iOS"),
            ]

    sent = []

    async def fake_send(items, **kw):
        sent.extend(items)
        return []

    from app.config import get_settings

    cfg = get_settings().scraper
    monkeypatch.setattr(cfg, "digest_email", "me@example.com")
    monkeypatch.setattr(job_feed, "SessionLocal", factory)
    monkeypatch.setattr(job_feed, "get_source", lambda name: FakeSource())
    monkeypatch.setattr(job_feed, "smtp_configured", lambda: True)
    monkeypatch.setattr(job_feed, "send_batch", fake_send)

    assert await job_feed.run_scheduled_refresh() == 2
    assert len(sent) == 1 and "Globex" in sent[0].body and "Initech" not in sent[0].body
    assert await job_feed.run_scheduled_refresh() == 0  # nothing new the second time
    assert len(sent) == 1
    assert factory().query(Application).count() == 0
