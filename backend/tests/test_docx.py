from app.resume.docx_render import render_docx
from app.schemas import ContactInfo, ExperienceItem, ResumeData


def test_render_docx_creates_file(tmp_path):
    resume = ResumeData(
        contact=ContactInfo(name="Jane Doe", email="jane@example.com"),
        summary="AI engineer.",
        skills=["Python", "PyTorch"],
        experience=[
            ExperienceItem(title="ML Engineer", company="Acme", bullets=["Built things."])
        ],
    )
    path = render_docx(resume, tmp_path, "resume_test")
    assert path.exists()
    assert path.suffix == ".docx"
    assert path.stat().st_size > 0


def test_render_docx_handles_empty_resume(tmp_path):
    path = render_docx(ResumeData(), tmp_path, "empty")
    assert path.exists()
