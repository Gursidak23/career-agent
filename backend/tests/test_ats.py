from app.resume.ats import extract_jd_keywords, score_resume
from app.schemas import (
    ContactInfo,
    EducationItem,
    ExperienceItem,
    ProjectItem,
    ResumeData,
)


def _strong_resume() -> ResumeData:
    return ResumeData(
        contact=ContactInfo(
            name="Jane Doe",
            email="jane@example.com",
            phone="+1 555 123 4567",
            linkedin="linkedin.com/in/janedoe",
            github="github.com/janedoe",
        ),
        summary="AI engineer building LLM and RAG systems in Python.",
        skills=[
            "Python", "PyTorch", "TensorFlow", "LLM", "RAG", "transformers",
            "Hugging Face", "Docker", "AWS", "MLOps", "embeddings", "NLP",
        ],
        experience=[
            ExperienceItem(
                title="ML Engineer",
                company="Acme",
                start_date="2021",
                end_date="Present",
                bullets=[
                    "Built a RAG pipeline that improved answer accuracy by 35%.",
                    "Reduced model inference latency by 40% using GPU batching.",
                    "Deployed transformers models to production serving 1M requests/day.",
                ],
            )
        ],
        projects=[
            ProjectItem(
                name="DocBot",
                tech=["Python", "LangChain", "embeddings"],
                bullets=["Designed vector database retrieval improving recall by 20%."],
            )
        ],
        education=[EducationItem(degree="BS Computer Science", institution="MIT")],
    )


def test_strong_resume_scores_well_for_ai_role():
    report = score_resume(_strong_resume(), "ai_engineer")
    assert report.score >= 70
    assert "python" in [k.lower() for k in report.matched_keywords]


def test_empty_resume_scores_low():
    report = score_resume(ResumeData(), "software_developer")
    assert report.score < 30
    assert report.suggestions


def test_extract_jd_keywords():
    jd = "We need Python, Kafka, and Airflow for our data pipeline on Snowflake."
    kws = extract_jd_keywords(jd)
    assert "python" in kws
    assert "kafka" in kws
    assert "airflow" in kws


def test_score_is_bounded():
    report = score_resume(_strong_resume(), "ai_engineer")
    assert 0 <= report.score <= 100
    for c in report.components:
        assert 0 <= c.score <= c.max


def test_synonym_matching():
    # "JS", "ML", "k8s" should match JavaScript, machine learning, Kubernetes.
    from app.resume.ats import _keyword_match

    text = "Experienced in JS and ML, deployed on k8s clusters."
    matched, _ = _keyword_match(text, ["javascript", "machine learning", "kubernetes"])
    assert set(matched) == {"javascript", "machine learning", "kubernetes"}


def test_fuzzy_matching_handles_minor_variation():
    from app.resume.ats import _keyword_match

    # "Tensorflow" vs "TensorFlow" and slight variations.
    matched, _ = _keyword_match("Built models with Tensorflow and PyTorch.", ["tensorflow", "pytorch"])
    assert "tensorflow" in matched
    assert "pytorch" in matched


def test_stuffing_penalty_applied():
    from app.resume.ats import _stuffing_factor

    clean = "python docker aws kafka"
    stuffed = " ".join(["python"] * 20 + ["docker"] * 20)
    assert _stuffing_factor(clean, ["python", "docker", "aws", "kafka"]) == 1.0
    assert _stuffing_factor(stuffed, ["python", "docker"]) < 1.0
