"""Output keeps the input resume's format, and tailoring stays truthful."""

import pymupdf
import pytest

from app.resume.latex import render_pdf, render_tex, tectonic_available
from app.resume.parser import extract_text, pdf_layout
from app.resume.tailor import lock_facts
from app.schemas import (
    CertificationItem,
    ContactInfo,
    EducationItem,
    ExperienceItem,
    ExtraSection,
    ProjectItem,
    ResumeData,
    ResumeLayout,
    SkillGroup,
)


def _resume(**overrides) -> ResumeData:
    data = ResumeData(
        contact=ContactInfo(
            name="Jane Doe",
            headline="Backend Engineer | APIs & Data",
            email="jane@example.com",
            linkedin="jane-doe",
            website="https://jane.dev/",
        ),
        summary="Backend engineer building Python services.",
        skill_groups=[
            SkillGroup(category="Languages", skills=["Python", "SQL"]),
            SkillGroup(category="Data & Cloud", skills=["PostgreSQL", "Docker"]),
        ],
        experience=[
            ExperienceItem(
                title="Software Engineer",
                company="Acme",
                location="Remote",
                start_date="Jan 2022",
                end_date="Present",
                bullets=[
                    "Built the OrderBot service in Python, cutting latency by 40% for 12 teams.",
                    "Migrated reports to PostgreSQL.",
                ],
            )
        ],
        projects=[
            ProjectItem(name="Crawler", link="https://github.com/jane/crawler", bullets=["Crawled 1M pages."])
        ],
        education=[
            EducationItem(
                degree="B.Tech CSE",
                institution="State University",
                start_date="2018",
                end_date="2022",
                details="GPA: 3.8/4.0\nRelevant Coursework: Algorithms, DBMS",
            )
        ],
        certifications=[CertificationItem(name="AWS SAA", date="2024 - 2027", url="https://cred.example/x#a")],
        extra_sections=[ExtraSection(title="Accomplishments", items=["Hackathon Lead, CodeFest: Led 15 people."])],
        section_order=["summary", "experience", "projects", "skills", "education", "certifications", "Accomplishments"],
        layout=ResumeLayout(page_size="letter", pages=1),
    )
    return data.model_copy(update=overrides)


def test_legacy_string_certifications_still_load():
    r = ResumeData.model_validate({"certifications": ["AWS SAA"]})
    assert r.certifications == [CertificationItem(name="AWS SAA")]


def test_skills_flatten_from_groups():
    assert _resume().skills == ["Python", "SQL", "PostgreSQL", "Docker"]


def test_template_follows_original_structure():
    tex = render_tex(_resume())
    assert "letterpaper" in tex
    assert "Backend Engineer \\textbar{} APIs \\& Data" not in tex  # headline is escaped, not split
    assert "Backend Engineer | APIs \\& Data" in tex
    assert "\\textbf{Languages:} Python, SQL" in tex
    assert "\\textbf{Data \\& Cloud:} PostgreSQL, Docker" in tex
    assert "https://linkedin.com/in/jane-doe" in tex and "{jane.dev}" in tex
    assert "\\href{https://github.com/jane/crawler}" in tex and "GitHub" in tex
    assert "\\href{https://cred.example/x\\#a}" in tex and "View credential" in tex
    assert "State University \\textbar{} 2018 - 2022 \\textbar{} GPA: 3.8/4.0" in tex
    assert "\\textbf{Relevant Coursework:} Algorithms, DBMS" in tex
    assert "\\textbf{Hackathon Lead, CodeFest:} Led 15 people." in tex
    order = [tex.index(f"\\sectionTitle{{{s}}}") for s in ("Summary", "Experience", "Projects", "Technical Skills", "Education", "Certifications", "Accomplishments")]
    assert order == sorted(order)


def test_section_order_is_respected():
    tex = render_tex(_resume(section_order=["education", "skills", "experience"]))
    assert tex.index("{Education}") < tex.index("{Technical Skills}") < tex.index("{Experience}")


def test_pdf_layout_and_links_are_extracted():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Crawler project GitHub " + "word " * 20)
    rect = pymupdf.Rect(150, 60, 190, 76)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": rect, "uri": "https://github.com/jane/crawler"})
    pdf = doc.tobytes()
    assert pdf_layout(pdf) == ResumeLayout(page_size="letter", pages=1)
    assert "LINKS:" in extract_text(pdf) and "https://github.com/jane/crawler" in extract_text(pdf)


def test_lock_facts_restores_facts_and_drops_fabrication():
    original = _resume()
    candidate = original.model_copy(
        update={
            "contact": original.contact.model_copy(update={"email": "evil@example.com"}),
            "experience": [
                ExperienceItem(
                    title="Staff Engineer",  # promoted by the model
                    company="Acme",
                    start_date="2019",
                    bullets=[
                        # Faithful rewrite with lowercase tech name: kept, recased.
                        "Engineered the OrderBot service in python, cutting latency by 40% for 12 teams.",
                        # Grafts Kubernetes, which the resume never mentions: reverted.
                        "Migrated reports to PostgreSQL on Kubernetes.",
                    ],
                )
            ],
            "skill_groups": [
                SkillGroup(category="Languages", skills=["Python", "SQL", "Go", "Rust"]),
                SkillGroup(category="Data & Cloud", skills=["PostgreSQL", "Docker", "Kubernetes"]),
            ],
        }
    )
    out, reviews = lock_facts(original, candidate)
    exp = out.experience[0]
    assert (exp.title, exp.start_date, exp.end_date) == ("Software Engineer", "Jan 2022", "Present")
    assert out.contact.email == "jane@example.com"
    assert exp.bullets[0] == "Engineered the OrderBot service in Python, cutting latency by 40% for 12 teams."
    assert exp.bullets[1] == "Migrated reports to PostgreSQL."
    assert "Kubernetes" not in out.skills and "Go" not in out.skills and "Rust" not in out.skills
    assert "Python" in out.skills and "python" not in out.skills
    assert out.certifications == original.certifications
    assert out.section_order == original.section_order
    # Both rewrites are offered for review; the clean one applied, the other held back.
    by_index = {r.index: r for r in reviews if r.section == "experience"}
    assert by_index[0].applied and not by_index[0].flags
    assert not by_index[1].applied and "Kubernetes" in by_index[1].flags[0]


def test_recase_only_fixes_names_not_ordinary_words():
    from app.resume.tailor import _casing_map, _recase

    r = _resume(skill_groups=[], skills=["Reranking", "Hybrid Search", "LangGraph", "PostgreSQL", "ONNX Runtime"])
    casing = _casing_map(r)
    assert _recase("reranking results with langgraph on postgresql via onnx runtime", casing) == (
        "reranking results with LangGraph on PostgreSQL via ONNX Runtime"
    )


def test_lock_facts_rejects_rewrites_that_drop_numbers_or_names():
    original = _resume()
    candidate = original.model_copy(
        update={
            "experience": [
                original.experience[0].model_copy(
                    update={
                        "bullets": [
                            "Built the PgPatent service in Python, cutting latency for many teams.",
                            "Moved reporting workloads onto PostgreSQL.",
                        ]
                    }
                )
            ]
        }
    )
    out, reviews = lock_facts(original, candidate)
    assert out.experience[0].bullets[0] == original.experience[0].bullets[0]
    assert out.experience[0].bullets[1] == "Moved reporting workloads onto PostgreSQL."
    held = next(r for r in reviews if r.index == 0)
    assert held.flags == ["Drops 40, 12, OrderBot"]


def test_apply_reviews_lets_user_accept_a_held_back_rewrite():
    from app.resume.tailor import apply_reviews

    original = _resume()
    candidate = original.model_copy(
        update={"experience": [original.experience[0].model_copy(update={"bullets": [
            original.experience[0].bullets[0], "Migrated reports to PostgreSQL on Kubernetes."]})]}
    )
    out, reviews = lock_facts(original, candidate)
    assert out.experience[0].bullets[1] == "Migrated reports to PostgreSQL."
    accepted = [r.model_copy(update={"applied": True}) for r in reviews]
    assert apply_reviews(out, accepted).experience[0].bullets[1] == "Migrated reports to PostgreSQL on Kubernetes."
    assert apply_reviews(out, reviews).experience[0].bullets[1] == "Migrated reports to PostgreSQL."


@pytest.mark.skipif(not tectonic_available(), reason="Tectonic not installed")
def test_long_resume_is_tightened_to_original_page_count(tmp_path):
    many = [f"Delivered feature number {i} improving reliability of the platform for users." for i in range(7)]
    exps = [
        ExperienceItem(title="Engineer", company=f"Company {i}", start_date="2020", end_date="2021", bullets=many)
        for i in range(5)  # 2 pages at the default spacing, 1 once tightened
    ]
    result = render_pdf(_resume(experience=exps), tmp_path, "fit")
    assert result.pdf_available
    with pymupdf.open(result.pdf_path) as doc:
        assert len(doc) == 1
