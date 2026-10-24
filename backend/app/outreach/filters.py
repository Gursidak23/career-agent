"""Reusable job-filtering helpers (job type, experience, role, location)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.sql import Select

from ..models import JobPosting

JOB_TYPES = ["full_time", "part_time", "contract", "internship", "freelance"]
EXPERIENCE_LEVELS = ["entry", "junior", "mid", "senior", "lead"]


def build_job_query(
    *,
    role_category: str | None = None,
    job_type: str | None = None,
    experience: str | None = None,
    location: str | None = None,
    company: str | None = None,
    has_email: bool | None = None,
    search: str | None = None,
) -> Select:
    stmt = select(JobPosting)
    if role_category:
        stmt = stmt.where(JobPosting.role_category == role_category)
    if job_type:
        stmt = stmt.where(JobPosting.job_type == job_type)
    if experience:
        stmt = stmt.where(JobPosting.experience == experience)
    if location:
        stmt = stmt.where(JobPosting.location.ilike(f"%{location}%"))
    if company:
        stmt = stmt.where(JobPosting.company.ilike(f"%{company}%"))
    if has_email is True:
        stmt = stmt.where(JobPosting.recruiter_email.is_not(None))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(JobPosting.title.ilike(like) | JobPosting.description.ilike(like))
    return stmt.order_by(JobPosting.created_at.desc())
