"""Resume history/reuse endpoints, friendly file names, outreach grounding, ATS fixes."""

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import Tailoring
from app.resume.ats import extract_jd_keywords, score_resume
from app.resume.naming import resume_filename
from app.routers import outreach as outreach_router
from app.routers import resume as resume_router
from app.routers.outreach import _profile
from app.schemas import (
    ContactInfo,
    EducationItem,
    ExperienceItem,
    GeneratedMessage,
    ResumeData,
)


def _parsed() -> ResumeData:
    return ResumeData(
        contact=ContactInfo(name="JANE DOE", email="jane@example.com"),
        skills=["Python", "SQL"],
        experience=[
            ExperienceItem(
                title="Engineer",
                company="Acme",
                bullets=["Built internal tools", "Cut API latency by 40% with Redis caching"],
            )
        ],
        education=[EducationItem(degree="BTech", institution="State University")],
    )


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def test_upload_reuses_identical_pdf_without_reparsing(client, monkeypatch):
    calls = []

    async def fake_structure(raw_text, layout=None):
        calls.append(raw_text)
        return _parsed(), None

    monkeypatch.setattr(resume_router, "structure_resume", fake_structure)
    pdf = _pdf_bytes("Jane Doe - Engineer at Acme - Python, SQL - BTech State University")
    files = {"file": ("cv.pdf", pdf, "application/pdf")}

    first = client.post("/api/resume/upload", files=files).json()
    second = client.post("/api/resume/upload", files=files).json()
    assert first["reused"] is False and second["reused"] is True
    assert second["resume_id"] == first["resume_id"]
    assert len(calls) == 1

    listed = client.get("/api/resume").json()
    assert [r["id"] for r in listed] == [first["resume_id"]]
    assert listed[0]["complete"] is True
    assert client.get(f"/api/resume/{first['resume_id']}").json()["parsed"]["contact"]["name"] == "JANE DOE"


def test_tailoring_history_and_reopen(client, monkeypatch):
    async def fake_structure(raw_text, layout=None):
        return _parsed(), None

    monkeypatch.setattr(resume_router, "structure_resume", fake_structure)
    pdf = _pdf_bytes("Jane Doe resume text for history")
    resume_id = client.post("/api/resume/upload", files={"file": ("cv.pdf", pdf, "application/pdf")}).json()["resume_id"]

    # Insert a tailoring directly (the real tailor endpoint needs an LLM).
    db = next(app.dependency_overrides[get_db]())
    improved = _parsed().model_copy(update={"summary": "Backend engineer"})
    report = score_resume(improved, "backend_engineer")
    db.add(
        Tailoring(
            resume_id=resume_id,
            role="backend_engineer",
            job_description="Backend Engineer at Globex\nWe need Python and SQL.",
            tailored=improved.model_dump(),
            ats_score=report.score,
            ats_report=report.model_dump(),
        )
    )
    db.commit()

    history = client.get(f"/api/resume/tailorings?resume_id={resume_id}").json()
    assert len(history) == 1
    assert history[0]["role_label"] == "Backend Engineer"
    assert history[0]["job_snippet"] == "Backend Engineer at Globex"

    reopened = client.get(f"/api/resume/tailorings/{history[0]['id']}").json()
    assert reopened["ats"]["score"] == report.score
    assert reopened["baseline_score"] is not None
    assert reopened["iterations"] is None


def test_resume_filename():
    assert resume_filename("JANE DOE", "backend_engineer", "pdf") == "Jane_Doe_Backend_Engineer_Resume.pdf"
    assert resume_filename("Ana-María O'Neil", "ai_engineer", ".docx") == "Ana_Mar_a_O_Neil_AI_Engineer_Resume.docx"
    assert resume_filename(None, "ai_engineer", "pdf") == "AI_Engineer_Resume.pdf"


def test_profile_prefers_quantified_bullets():
    prof = _profile(Tailoring(tailored=_parsed().model_dump(), role="backend_engineer"))
    assert prof.candidate_name == "Jane Doe"
    assert prof.highlights[0].startswith("Cut API latency by 40%")


@pytest.mark.asyncio
async def test_generate_fills_context_from_tailoring_and_job(client, monkeypatch):
    seen = {}

    async def fake_generate(req):
        seen["req"] = req
        return [GeneratedMessage(channel="email", subject="Hi", body="Hello")], None

    monkeypatch.setattr(outreach_router, "generate_messages", fake_generate)
    db = next(app.dependency_overrides[get_db]())
    t = Tailoring(resume_id=1, role="backend_engineer", tailored=_parsed().model_dump())
    db.add(t)
    db.commit()

    res = client.post(
        "/api/outreach/generate",
        json={"company": "Globex", "role": "Backend Engineer", "tailoring_id": t.id,
              "job_description": "We need Python."},
    )
    assert res.status_code == 200
    req = seen["req"]
    assert req.candidate_name == "Jane Doe"
    assert req.candidate_highlights and "40%" in req.candidate_highlights[0]
    assert req.job_description == "We need Python."


def test_jd_keywords_use_word_boundaries():
    keys = extract_jd_keywords("We want a good engineer who knows Python and React.")
    assert "python" in keys and "react" in keys
    assert "go" not in keys and "r" not in keys


def test_linux_is_not_a_metric():
    resume = _parsed().model_copy(
        update={"experience": [ExperienceItem(title="E", company="C", bullets=["Managed Linux servers"])]}
    )
    detail = next(c for c in score_resume(resume, "devops_engineer").components if c.name == "Quantified achievements")
    assert "50%" in detail.detail  # verb only, no metric -> half credit
