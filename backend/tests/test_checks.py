"""ATS read-back, recruiter scan, requirement evidence, and interview drill."""

from datetime import date

import pymupdf
import pytest

from app.resume import drill, evidence
from app.resume.ats_check import check_pdf
from app.resume.latex import render_pdf, tectonic_available
from app.resume.scan import scan_pdf
from app.schemas import ContactInfo, ExperienceItem, ProjectItem, ResumeData

RESUME = ResumeData(
    contact=ContactInfo(name="Jane Doe", headline="Backend Engineer", email="jane@example.com", phone="+1 555 123 4567"),
    summary="Backend engineer building Python services.",
    skills=["Python", "PostgreSQL", "Docker"],
    experience=[
        ExperienceItem(
            title="Software Engineer",
            company="Acme",
            start_date="Jan 2022",
            end_date="Jan 2024",
            bullets=["Cut API latency by 40% with Redis caching.", "Certified the official deployment pipeline."],
        ),
        ExperienceItem(title="Intern", company="Beta", start_date="Jan 2021", end_date="Jan 2022", bullets=["Wrote tests."]),
    ],
    projects=[ProjectItem(name="Crawler", bullets=["Crawled 1M pages on Python asyncio."])],
)


def _pdf(tmp_path, text: str):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=10)
    path = tmp_path / "r.pdf"
    doc.save(path)
    return path


def _plain_text(r: ResumeData) -> str:
    lines = [r.contact.name, r.contact.headline, r.contact.email, r.contact.phone, "SUMMARY", r.summary, "EXPERIENCE"]
    for e in r.experience:
        lines += [f"{e.company} {e.title}", *(f"- {b}" for b in e.bullets)]
    lines += ["PROJECTS", "Crawler", *(f"- {b}" for b in r.projects[0].bullets), "SKILLS", ", ".join(r.skills)]
    return "\n".join(lines)


# ----------------------------------------------------------------- ATS check --
def test_ats_check_clean_pdf_scores_high(tmp_path):
    report = check_pdf(_pdf(tmp_path, _plain_text(RESUME)), RESUME)
    assert report.verdict == "excellent"
    assert {e.name for e in report.extractors} == {"PyMuPDF", "pdfminer.six", "pypdf"}
    assert all(e.word_coverage == 100 for e in report.extractors)


def test_ats_check_flags_ligatures_missing_words_and_contact(tmp_path):
    text = _plain_text(RESUME).replace("Certified", "Ceriﬁed").replace("jane@example.com", "").replace("Redis", "")
    report = check_pdf(_pdf(tmp_path, text), RESUME)
    issues = " ".join(report.extractors[0].issues)
    assert "Ligatures" in issues or "missing" in issues
    assert "Email address not recoverable" in issues
    assert report.score < 100


@pytest.mark.skipif(not tectonic_available(), reason="Tectonic not installed")
def test_rendered_resume_reads_back_perfectly(tmp_path):
    """Regression: ligatures and kerned capitals used to break extraction."""
    result = render_pdf(RESUME, tmp_path, "r")
    report = check_pdf(result.pdf_path, RESUME)
    assert report.score == 100, [e.issues for e in report.extractors]


# ---------------------------------------------------------------------- scan --
def test_scan_finds_top_content_and_buried_keywords(tmp_path):
    filler = "\n".join(f"Filler line {i} about general responsibilities." for i in range(45))
    text = f"Jane Doe\nBackend Engineer\nSummary: builds services.\n{filler}\nSkills: Python, PostgreSQL, Docker"
    report, png = scan_pdf(_pdf(tmp_path, text), RESUME, "backend_engineer", None)
    assert png[:4] == b"\x89PNG"
    assert report.seen_text.startswith("Jane Doe")
    assert report.seen_words <= 110
    assert "Python" in report.keywords_buried
    assert any("first-glance" in tip for tip in report.tips)


# ------------------------------------------------------------------ evidence --
def test_candidate_years_counts_internships_half():
    assert evidence.candidate_years(RESUME, today=date(2025, 1, 1)) == 2.5


def test_evidence_lines_are_numbered_and_labelled():
    lines = evidence.resume_lines(RESUME)
    assert [ln.id for ln in lines] == list(range(1, len(lines) + 1))
    assert any(ln.where == "Acme" and "40%" in ln.text for ln in lines)


@pytest.mark.asyncio
async def test_evidence_drops_invented_citations_and_adds_years_flag(monkeypatch):
    async def fake_llm(system, prompt, **kw):
        return {
            "requirements": [
                {"text": "Python", "kind": "must", "evidence": [3, "L4"], "status": "met", "note": "ok"},
                {"text": "Kubernetes", "kind": "must", "evidence": [999], "status": "met", "note": "claims"},
                {"text": "Kafka", "kind": "nice", "evidence": [], "status": "gap", "note": "learn it"},
            ],
            "red_flags": [{"text": "No salary listed", "why": "Ask early."}],
        }

    monkeypatch.setattr(evidence, "complete_json", fake_llm)
    report = await evidence.analyze(RESUME, "We need Python and Kubernetes. 8+ years of experience. Kafka is a plus. " * 2)
    by_text = {r.text: r for r in report.requirements}
    assert by_text["Python"].status == "met" and [e.id for e in by_text["Python"].evidence] == [3, 4]
    assert by_text["Kubernetes"].status == "gap" and not by_text["Kubernetes"].evidence
    assert (report.must_met, report.must_total, report.nice_total) == (1, 2, 1)
    assert report.red_flags[0].text.startswith("Asks for 8+ years")
    assert report.years_required == 8


# --------------------------------------------------------------------- drill --
def test_drill_claims_put_quantified_bullets_first():
    picked = drill.claims(RESUME, count=2)
    assert all(any(ch.isdigit() for ch in c.text) for c in picked)


@pytest.mark.asyncio
async def test_drill_grade_short_answer_needs_no_llm(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(drill, "complete_json", boom)
    g = await drill.grade("Cut latency by 40%.", "How measured?", [], "it was faster")
    assert g.verdict == "undefended" and g.score == 1


@pytest.mark.asyncio
async def test_drill_safer_wording_cannot_add_technologies(monkeypatch):
    async def fake(system, prompt, **kw):
        return {"verdict": "shaky", "score": 2, "feedback": "Vague.", "follow_up": "null",
                "safer_wording": "Cut API latency with Redis caching on Kubernetes."}

    monkeypatch.setattr(drill, "complete_json", fake)
    g = await drill.grade("Cut API latency by 40% with Redis caching.", "How?", [], "We added a Redis cache in front of the API.")
    assert g.verdict == "shaky" and g.safer_wording is None and g.follow_up is None


@pytest.mark.asyncio
async def test_drill_questions_ignore_unknown_claims(monkeypatch):
    async def fake(system, prompt, **kw):
        return {"questions": [{"claim_id": 1, "question": "How did you measure 40%?", "look_for": ["baseline"]},
                              {"claim_id": 42, "question": "Invented?"}]}

    monkeypatch.setattr(drill, "complete_json", fake)
    qs = await drill.questions(RESUME, count=3)
    assert [q.claim_id for q in qs] == [1] and "40%" in qs[0].claim
