"""ATS read-back: what text-extraction tools actually recover from a resume PDF.

Applicant tracking systems don't see the page; they see whatever their PDF text
extractor returns. This runs three independent extractors (PyMuPDF, pdfminer.six,
pypdf) and compares each one's output with the structured resume to catch:
missing words, words split across lines, undecodable glyphs/ligatures, sections
out of order, unreadable contact details, and bullets whose text got jumbled.
The worst extractor sets the verdict: you can't know which parser an ATS uses.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from ..schemas import AtsCheckReport, ExtractorResult, ResumeData

_WORD = re.compile(r"[a-z0-9][a-z0-9+#]*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LIGATURES = "ﬀﬁﬂﬃﬄﬅﬆ"
_SECTION_TITLES = {
    "summary": "Summary",
    "experience": "Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
}


def _extract_pymupdf(pdf: bytes) -> str:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return "\n".join(page.get_text("text") for page in doc)


def _extract_pdfminer(pdf: bytes) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(io.BytesIO(pdf))


def _extract_pypdf(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


EXTRACTORS = {
    "PyMuPDF": _extract_pymupdf,
    "pdfminer.six": _extract_pdfminer,
    "pypdf": _extract_pypdf,
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("­", "").lower()).strip()


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 3}


def _expected_text(resume: ResumeData) -> str:
    c = resume.contact
    parts = [c.name, c.headline or "", resume.summary or ""]
    parts += [s for s in resume.skills]
    for e in resume.experience:
        parts += [e.title, e.company, *e.bullets]
    for p in resume.projects:
        parts += [p.name, p.description or "", *p.bullets]
    for ed in resume.education:
        parts += [ed.degree, ed.institution]
    parts += [x.name for x in resume.certifications]
    for x in resume.extra_sections:
        parts += x.items
    return "\n".join(parts)


def _section_titles(resume: ResumeData) -> list[str]:
    titles = []
    for key in resume.ordered_sections():
        if key == "skills":
            titles.append("Technical Skills" if resume.skill_groups else "Skills")
        else:
            titles.append(_SECTION_TITLES.get(key, key))
    return titles


def _check(name: str, text: str, resume: ResumeData) -> ExtractorResult:
    issues: list[str] = []
    norm = _norm(text)
    compact = re.sub(r"[\s\-]", "", norm)

    expected = _words(_expected_text(resume))
    found = _words(norm)
    missing = sorted(expected - found)
    split = [w for w in missing if w in compact]
    lost = [w for w in missing if w not in compact]
    coverage = 1 - len(missing) / len(expected) if expected else 1.0
    if split:
        issues.append(f"{len(split)} word(s) broken apart (line breaks or letter spacing), e.g. {', '.join(split[:4])}")
    if lost:
        issues.append(f"{len(lost)} word(s) missing entirely, e.g. {', '.join(lost[:4])}")

    bad_glyphs = text.count("�") + text.count("(cid:") + sum(1 for ch in text if "" <= ch <= "")
    ligatures = sorted({ch for ch in text if ch in _LIGATURES})
    if bad_glyphs:
        issues.append(f"{bad_glyphs} undecodable character(s): text an ATS cannot read")
    if ligatures:
        issues.append(f"Ligatures not expanded ({' '.join(ligatures)}): words like 'profile' may not match")

    positions = []
    for title in _section_titles(resume):
        idx = norm.find(title.lower())
        if idx < 0:
            issues.append(f"Section heading '{title}' not found")
        positions.append(idx)
    present = [p for p in positions if p >= 0]
    if present != sorted(present):
        issues.append("Sections come out in a different order than on the page")

    c = resume.contact
    if c.email and c.email.lower() not in norm.replace(" ", ""):
        issues.append("Email address not recoverable")
    digits = re.sub(r"\D", "", c.phone or "")
    if digits and digits[-7:] not in re.sub(r"\D", "", norm):
        issues.append("Phone number not recoverable")

    bullets = [b for e in resume.experience for b in e.bullets] + [b for p in resume.projects for b in p.bullets]
    intact = 0
    for b in bullets:
        head = " ".join(_norm(b).split()[:6])
        if head and head in norm:
            intact += 1
    intact_ratio = intact / len(bullets) if bullets else 1.0
    if bullets and intact < len(bullets):
        issues.append(f"{len(bullets) - intact} of {len(bullets)} bullets don't read back in order")

    score = round(
        100
        * (
            0.5 * coverage
            + 0.3 * intact_ratio
            + 0.2 * (1.0 if not (bad_glyphs or ligatures or present != sorted(present)) else 0.4)
        )
    )
    return ExtractorResult(
        name=name,
        score=score,
        word_coverage=round(100 * coverage, 1),
        bullets_intact=round(100 * intact_ratio, 1),
        issues=issues,
        preview=text.strip()[:1800],
    )


def check_pdf(pdf_path: Path, resume: ResumeData) -> AtsCheckReport:
    pdf = pdf_path.read_bytes()
    results = []
    for name, extract in EXTRACTORS.items():
        try:
            text = extract(pdf)
        except Exception as exc:  # noqa: BLE001 - a crashing parser is itself a finding
            results.append(ExtractorResult(name=name, score=0, issues=[f"Extractor failed: {exc}"]))
            continue
        results.append(_check(name, text, resume))

    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        links = [link.get("uri") for page in doc for link in page.get_links() if link.get("uri")]
    hidden = [u for u in links if u and not u.startswith("mailto:") and _norm(u.split("//")[-1]).rstrip("/") not in _norm(
        "\n".join(r.preview for r in results)
    )]
    notes = []
    if hidden:
        notes.append(
            f"{len(hidden)} link(s) sit behind anchor text (e.g. 'GitHub'); text-only parsers "
            "keep the label but not the URL. Fine for humans, invisible to keyword search."
        )

    worst = min((r.score for r in results), default=0)
    verdict = "excellent" if worst >= 92 else "good" if worst >= 80 else "risky"
    return AtsCheckReport(verdict=verdict, score=worst, extractors=results, notes=notes)
