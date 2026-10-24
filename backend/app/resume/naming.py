"""Human-friendly file names for downloads and email attachments.

Recruiters see the attachment name, so ``Jane_Doe_Backend_Engineer_Resume.pdf``
beats ``resume_12.pdf``.
"""

from __future__ import annotations

import re

from .roles import get_role


def resume_filename(candidate_name: str | None, role: str, ext: str) -> str:
    name = (candidate_name or "").strip()
    if name.isupper():  # "JANE DOE" -> "Jane Doe"
        name = name.title()
    stem = "_".join(p for p in (name, get_role(role).label, "Resume") if p)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_")
    return f"{stem or 'Resume'}.{ext.lstrip('.')}"
