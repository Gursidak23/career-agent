"""Technical role profiles with curated keyword/skill banks.

Used by the ATS scorer (keyword coverage) and the tailor (what to emphasize).
When a job description is provided, keywords extracted from it take priority,
and these banks act as a sensible baseline / fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleProfile:
    key: str
    label: str
    # Core hard skills/keywords ATS systems look for.
    keywords: list[str] = field(default_factory=list)
    # Short guidance injected into the tailoring prompt.
    emphasis: str = ""


ROLES: dict[str, RoleProfile] = {
    "ai_engineer": RoleProfile(
        key="ai_engineer",
        label="AI Engineer",
        keywords=[
            "Python", "PyTorch", "TensorFlow", "machine learning", "deep learning",
            "LLM", "large language models", "transformers", "Hugging Face", "NLP",
            "RAG", "vector database", "embeddings", "fine-tuning", "prompt engineering",
            "MLOps", "model deployment", "inference", "scikit-learn", "pandas", "numpy",
            "data pipelines", "GPU", "CUDA", "feature engineering", "evaluation",
            "LangChain", "OpenAI API", "REST API", "Docker", "AWS",
        ],
        emphasis=(
            "Highlight ML/LLM project impact, model metrics, datasets, and "
            "production deployment of AI systems."
        ),
    ),
    "software_developer": RoleProfile(
        key="software_developer",
        label="Software Developer",
        keywords=[
            "Java", "Python", "C++", "JavaScript", "TypeScript", "Go", "data structures",
            "algorithms", "object-oriented programming", "REST API", "microservices",
            "SQL", "NoSQL", "Git", "CI/CD", "unit testing", "Docker", "Kubernetes",
            "system design", "Agile", "Scrum", "design patterns", "multithreading",
            "AWS", "distributed systems", "debugging", "code review",
        ],
        emphasis=(
            "Emphasize systems built, scale handled, languages, and measurable "
            "performance or reliability improvements."
        ),
    ),
    "web_developer": RoleProfile(
        key="web_developer",
        label="Web Developer",
        keywords=[
            "JavaScript", "TypeScript", "React", "Next.js", "Vue", "Angular", "HTML",
            "CSS", "Tailwind", "Node.js", "Express", "REST API", "GraphQL", "Redux",
            "responsive design", "accessibility", "webpack", "Vite", "SQL", "MongoDB",
            "authentication", "testing", "Jest", "CI/CD", "Docker", "AWS", "performance",
        ],
        emphasis=(
            "Emphasize shipped web features, frontend/backend stack, performance, "
            "and UX/accessibility outcomes."
        ),
    ),
    "data_engineer": RoleProfile(
        key="data_engineer",
        label="Data Engineer",
        keywords=[
            "Python", "SQL", "Spark", "Hadoop", "Kafka", "Airflow", "ETL", "ELT",
            "data pipeline", "data warehouse", "Snowflake", "BigQuery", "Redshift",
            "dbt", "data modeling", "batch processing", "stream processing", "AWS",
            "GCP", "Azure", "Docker", "Kubernetes", "Parquet", "data lake", "Scala",
            "orchestration", "data quality",
        ],
        emphasis=(
            "Emphasize data volume/throughput, pipeline reliability, latency, and "
            "warehouse/lake architecture."
        ),
    ),
    "app_developer": RoleProfile(
        key="app_developer",
        label="App Developer (Mobile)",
        keywords=[
            "Kotlin", "Swift", "Java", "Android", "iOS", "Flutter", "Dart",
            "React Native", "Jetpack Compose", "SwiftUI", "REST API", "SQLite",
            "Firebase", "MVVM", "Gradle", "Xcode", "push notifications", "CI/CD",
            "unit testing", "Play Store", "App Store", "performance", "UI/UX",
        ],
        emphasis=(
            "Emphasize shipped apps, install/usage numbers, platform stack, and "
            "store releases."
        ),
    ),
    "devops_engineer": RoleProfile(
        key="devops_engineer",
        label="DevOps Engineer",
        keywords=[
            "Docker", "Kubernetes", "Terraform", "Ansible", "CI/CD", "Jenkins",
            "GitHub Actions", "AWS", "GCP", "Azure", "Linux", "Bash", "Python",
            "monitoring", "Prometheus", "Grafana", "observability", "IaC", "Helm",
            "networking", "security", "SRE", "incident response", "scalability",
        ],
        emphasis=(
            "Emphasize automation, uptime/SLOs, infrastructure scale, and "
            "deployment frequency improvements."
        ),
    ),
    "data_scientist": RoleProfile(
        key="data_scientist",
        label="Data Scientist",
        keywords=[
            "Python", "R", "SQL", "machine learning", "statistics", "pandas", "numpy",
            "scikit-learn", "data visualization", "A/B testing", "experimentation",
            "regression", "classification", "clustering", "feature engineering",
            "Jupyter", "Tableau", "Power BI", "hypothesis testing", "deep learning",
            "model evaluation", "business impact",
        ],
        emphasis=(
            "Emphasize experiments run, models built, statistical rigor, and "
            "business metrics moved."
        ),
    ),
    "backend_engineer": RoleProfile(
        key="backend_engineer",
        label="Backend Engineer",
        keywords=[
            "Java", "Python", "Go", "Node.js", "REST API", "GraphQL", "microservices",
            "SQL", "PostgreSQL", "NoSQL", "Redis", "Kafka", "message queue",
            "system design", "caching", "scalability", "Docker", "Kubernetes", "AWS",
            "CI/CD", "unit testing", "distributed systems", "performance",
        ],
        emphasis=(
            "Emphasize API/service design, throughput/latency, data stores, and "
            "reliability at scale."
        ),
    ),
}


def role_keys() -> list[str]:
    return list(ROLES.keys())


def get_role(key: str) -> RoleProfile:
    """Look up a role by key or (case-insensitive) label; fall back to SWE."""
    if key in ROLES:
        return ROLES[key]
    norm = key.strip().lower().replace(" ", "_").replace("-", "_")
    if norm in ROLES:
        return ROLES[norm]
    for profile in ROLES.values():
        if profile.label.lower() == key.strip().lower():
            return profile
    return ROLES["software_developer"]
