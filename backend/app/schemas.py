"""Pydantic schemas: structured resume data + API request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# --------------------------------------------------------------------------- #
# Structured resume representation (produced by the parser, consumed by the
# tailor, ATS scorer, and LaTeX renderer).
# --------------------------------------------------------------------------- #
class ContactInfo(BaseModel):
    name: str = ""
    # Tagline under the name, e.g. "AI Engineer | LLMs, RAG & Agentic Systems".
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class ExperienceItem(BaseModel):
    title: str = ""
    company: str = ""
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bullets: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str = ""
    description: str | None = None
    tech: list[str] = Field(default_factory=list)
    link: str | None = None
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    degree: str = ""
    institution: str = ""
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: str | None = None


class SkillGroup(BaseModel):
    category: str = ""
    skills: list[str] = Field(default_factory=list)


class CertificationItem(BaseModel):
    name: str = ""
    date: str | None = None
    url: str | None = None


class ExtraSection(BaseModel):
    """Any other section (Accomplishments, Awards, Publications, ...)."""

    title: str = ""
    items: list[str] = Field(default_factory=list)


class ResumeLayout(BaseModel):
    """Properties of the uploaded PDF that the rendered output should keep."""

    page_size: str | None = None  # "letter" | "a4"
    pages: int | None = None


# Keys for section_order; extra sections use their own titles.
STANDARD_SECTIONS = ("summary", "experience", "projects", "skills", "education", "certifications")


class ResumeData(BaseModel):
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str | None = None
    # Flat list (used for scoring). Mirrors skill_groups when those are present.
    skills: list[str] = Field(default_factory=list)
    # Categorized skills as the original resume groups them, if it does.
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    extra_sections: list[ExtraSection] = Field(default_factory=list)
    # Section order of the original resume (STANDARD_SECTIONS keys + extra titles).
    section_order: list[str] = Field(default_factory=list)
    layout: ResumeLayout = Field(default_factory=ResumeLayout)

    @field_validator("certifications", mode="before")
    @classmethod
    def _certs_from_strings(cls, value: object) -> object:
        # Older records (and some LLM replies) store certifications as plain strings.
        if isinstance(value, list):
            return [{"name": v} if isinstance(v, str) else v for v in value]
        return value

    @model_validator(mode="after")
    def _sync_skills(self) -> ResumeData:
        if self.skill_groups:
            flat = [s for g in self.skill_groups for s in g.skills]
            known = {s.lower() for s in flat}
            # Keep flat-only skills too, so nothing the scorer sees is lost.
            self.skills = flat + [s for s in self.skills if s.lower() not in known]
        return self

    def ordered_sections(self) -> list[str]:
        """Sections to render, in the original order, then any not listed there."""
        present = {
            "summary": bool(self.summary),
            "experience": bool(self.experience),
            "projects": bool(self.projects),
            "skills": bool(self.skills),
            "education": bool(self.education),
            "certifications": bool(self.certifications),
        }
        present.update({x.title: bool(x.items) for x in self.extra_sections})
        by_lower = {k.lower(): k for k in present}
        order: list[str] = []
        for key in [*self.section_order, *STANDARD_SECTIONS, *(x.title for x in self.extra_sections)]:
            k = by_lower.get(key.strip().lower())
            if k and present[k] and k not in order:
                order.append(k)
        return order


# --------------------------------------------------------------------------- #
# ATS scoring
# --------------------------------------------------------------------------- #
class AtsComponent(BaseModel):
    name: str
    score: float  # 0..max
    max: float
    detail: str = ""


class AtsReport(BaseModel):
    score: float  # 0..100
    components: list[AtsComponent] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Resume API
# --------------------------------------------------------------------------- #
class UploadResponse(BaseModel):
    resume_id: int
    parsed: ResumeData
    raw_text_chars: int
    warning: str | None = None
    # True when an identical PDF was uploaded before and its parse was reused.
    reused: bool = False


class ResumeSummary(BaseModel):
    id: int
    created_at: datetime
    filename: str | None = None
    name: str = ""
    complete: bool  # False for degraded (heuristic) parses with no sections


class TailoringSummary(BaseModel):
    id: int
    resume_id: int
    created_at: datetime
    role: str
    role_label: str
    ats_score: float | None = None
    job_snippet: str | None = None


class TailorRequest(BaseModel):
    resume_id: int
    role: str
    job_description: str | None = None
    target_score: float = 90.0
    max_iterations: int = 4


class TailorResponse(BaseModel):
    tailoring_id: int
    resume_id: int
    role: str
    tailored: ResumeData
    ats: AtsReport
    iterations: int | None = None  # not stored, so None when reopened from history
    pdf_available: bool
    docx_available: bool = False
    warning: str | None = None
    # Score of the original resume for the same role/JD, to show the improvement.
    baseline_score: float | None = None
    job_description: str | None = None


class ScoreRequest(BaseModel):
    resume: ResumeData
    role: str
    job_description: str | None = None


# --------------------------------------------------------------------------- #
# Outreach API
# --------------------------------------------------------------------------- #
class MessageGenRequest(BaseModel):
    recruiter_name: str | None = None
    company: str
    role: str
    channel: str = "email"  # email | linkedin
    candidate_name: str | None = None
    candidate_highlights: list[str] = Field(default_factory=list)
    job_id: int | None = None
    tone: str = "professional"  # professional | warm | concise
    variants: int = 2
    # Optional context. When omitted, the route fills them from job_id / tailoring_id.
    job_description: str | None = None
    tailoring_id: int | None = None


class GeneratedMessage(BaseModel):
    channel: str
    subject: str | None = None
    body: str


class CandidateProfile(BaseModel):
    candidate_name: str = ""
    highlights: list[str] = Field(default_factory=list)


class MessageGenResponse(BaseModel):
    messages: list[GeneratedMessage]
    warning: str | None = None


class SendItem(BaseModel):
    to_email: EmailStr
    subject: str
    body: str
    recruiter_name: str | None = None
    company: str | None = None
    role: str | None = None
    # Optional: attach this tailoring's generated resume (PDF) to the email.
    tailoring_id: int | None = None


class BatchSendRequest(BaseModel):
    items: list[SendItem]
    dry_run: bool = False


class SendResult(BaseModel):
    to_email: str
    status: str
    error: str | None = None


class BatchSendResponse(BaseModel):
    results: list[SendResult]
    sent: int
    failed: int
    queued: int = 0


class EmailLogOut(BaseModel):
    id: int
    to_email: str
    subject: str | None = None
    status: str
    error: str | None = None

    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------- #
# Email finder API
# --------------------------------------------------------------------------- #
class EmailFindRequest(BaseModel):
    company: str
    name: str | None = None
    domain: str | None = None
    job_url: str | None = None
    job_id: int | None = None


class EmailCandidateOut(BaseModel):
    email: str
    source: str
    confidence: float
    verified: str  # unverified | mx_only | verified
    name: str | None = None


class EmailFindResponse(BaseModel):
    candidates: list[EmailCandidateOut]
    best: EmailCandidateOut | None = None
    domain: str | None = None


class EmailVerifyRequest(BaseModel):
    email: EmailStr


class EmailVerifyResponse(BaseModel):
    email: str
    verified: str


# --------------------------------------------------------------------------- #
# LinkedIn DM API
# --------------------------------------------------------------------------- #
class LinkedInSendItem(BaseModel):
    profile_url: str
    message: str
    recipient_name: str | None = None
    message_id: int | None = None


class LinkedInBatchRequest(BaseModel):
    items: list[LinkedInSendItem]
    dry_run: bool = False


class LinkedInBatchResponse(BaseModel):
    results: list[SendResult]
    sent: int
    failed: int
    queued: int = 0


class LinkedInLogOut(BaseModel):
    id: int
    profile_url: str
    recipient_name: str | None = None
    status: str
    error: str | None = None

    model_config = {"from_attributes": True}


class LinkedInStatus(BaseModel):
    enabled: bool
    playwright_available: bool
    logged_in: bool


# --------------------------------------------------------------------------- #
# Jobs API
# --------------------------------------------------------------------------- #
class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    location: str | None = None
    job_type: str | None = None
    experience: str | None = None
    role_category: str | None = None
    url: str | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    description: str | None = None

    model_config = {"from_attributes": True}


class JobRefreshRequest(BaseModel):
    source: str = "all"
    query: str | None = None
    location: str | None = None
    limit: int = 25
    # When true, run the email finder for postings missing a recruiter email.
    enrich_emails: bool = False


# --------------------------------------------------------------------------- #
# Settings API
# --------------------------------------------------------------------------- #
class ProviderStatus(BaseModel):
    name: str
    configured: bool
    model: str


class EmailProviderStatus(BaseModel):
    name: str
    enabled: bool


class ConnectionTest(BaseModel):
    name: str
    ok: bool
    latency_ms: int | None = None
    detail: str = ""


class SettingsStatus(BaseModel):
    providers: list[ProviderStatus]
    smtp_configured: bool
    tectonic_available: bool
    roles: list[str]
    email_providers: list[EmailProviderStatus] = Field(default_factory=list)
    linkedin_enabled: bool = False
    linkedin_available: bool = False
    # Shell variables overriding different .env values (stale terminal env).
    env_overrides: list[str] = Field(default_factory=list)
