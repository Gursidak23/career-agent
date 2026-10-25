"""Parse an uploaded resume PDF into structured ResumeData.

Strategy: extract text with PyMuPDF, then ask the LLM to structure it into the
ResumeData schema. If no LLM is configured (or it fails), fall back to a small
regex-based extractor so the app still works in a degraded mode.
"""

from __future__ import annotations

import re

from ..llm import LlmError
from ..llm.router import complete_json
from ..logging_setup import get_logger
from ..schemas import ContactInfo, ResumeData, ResumeLayout

log = get_logger(__name__)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_LINKEDIN = re.compile(r"(https?://)?(www\.)?linkedin\.com/[\w/-]+", re.IGNORECASE)
_GITHUB = re.compile(r"(https?://)?(www\.)?github\.com/[\w/-]+", re.IGNORECASE)


# Below this many extracted characters we assume the PDF is scanned/image-based.
_OCR_THRESHOLD = 50


def _ocr_pages(doc) -> str:
    """OCR every page (PyMuPDF -> Tesseract). Raises ValueError if unavailable."""
    out: list[str] = []
    for page in doc:
        try:
            textpage = page.get_textpage_ocr(flags=0, full=True)
            out.append(page.get_text("text", textpage=textpage))
        except Exception as exc:  # noqa: BLE001 - Tesseract missing or OCR error
            raise ValueError(
                "This looks like a scanned/image PDF and OCR is unavailable. "
                "Install Tesseract OCR (and ensure TESSDATA_PREFIX is set) to parse it, "
                "or upload a text-based PDF."
            ) from exc
    return "\n".join(out).strip()


def _links(doc) -> list[str]:
    """Hyperlink targets with their anchor text and surrounding line.

    Anchors like "GitHub" or "View credential" hide their URL from the visible
    text, so without this the parser could never keep those links.
    """
    import pymupdf

    out: list[str] = []
    for page in doc:
        for link in page.get_links():
            uri = link.get("uri")
            if not uri or uri.startswith("mailto:"):
                continue
            rect = link["from"]
            label = " ".join(page.get_textbox(rect).split())
            line = " ".join(page.get_textbox(pymupdf.Rect(0, rect.y0, page.rect.width, rect.y1)).split())
            out.append(f'"{label}" on line "{line}" -> {uri}')
    return list(dict.fromkeys(out))


def extract_text(pdf_bytes: bytes) -> str:
    """Extract selectable text (plus a LINKS appendix); fall back to OCR for scans."""
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        text = "\n".join(page.get_text("text") for page in doc).strip()
        if len(text) < _OCR_THRESHOLD:
            return _ocr_pages(doc)
        links = _links(doc)
        return text + ("\n\nLINKS:\n" + "\n".join(links) if links else "")
    finally:
        doc.close()


def pdf_layout(pdf_bytes: bytes) -> ResumeLayout:
    """Page size and count of the uploaded PDF, so the output can match them."""
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        height = doc[0].rect.height if len(doc) else 0
        size = "a4" if abs(height - 842) < 15 else "letter" if abs(height - 792) < 15 else None
        return ResumeLayout(page_size=size, pages=len(doc))
    finally:
        doc.close()


_STRUCTURE_SYSTEM = (
    "You are an expert resume parser. Convert the raw resume text into a single "
    "JSON object. Extract information faithfully and completely; never invent facts, "
    "and copy bullets verbatim. If a field is unknown, use null or an empty array. "
    "Return ONLY the JSON object."
)

# Shared with the tailor so both speak the same shape.
SCHEMA_HINT = """
ResumeData JSON shape:
{
  "contact": {"name": str, "headline": str|null, "email": str|null, "phone": str|null,
              "location": str|null, "linkedin": str|null, "github": str|null,
              "website": str|null},
  "summary": str|null,
  "skills": [str],
  "skill_groups": [{"category": str, "skills": [str]}],
  "experience": [{"title": str, "company": str, "location": str|null,
                  "start_date": str|null, "end_date": str|null, "bullets": [str]}],
  "projects": [{"name": str, "description": str|null, "tech": [str],
                "link": str|null, "bullets": [str]}],
  "education": [{"degree": str, "institution": str, "location": str|null,
                 "start_date": str|null, "end_date": str|null, "details": str|null}],
  "certifications": [{"name": str, "date": str|null, "url": str|null}],
  "extra_sections": [{"title": str, "items": [str]}],
  "section_order": [str]
}
""".strip()

_PARSE_RULES = """
Rules:
- contact.headline: the tagline under the name (e.g. "AI Engineer | LLMs & RAG"), if any.
- skill_groups: if skills are grouped under labels ("Languages: ..."), reproduce every
  group in order with its exact label; "skills" is then all of them flattened.
- certifications: each with its validity/date text and its URL from LINKS, if any.
- projects[].link: the project's URL from LINKS (e.g. a GitHub link), if any.
- education[].details: everything else in the entry (grade, coursework), one item
  per line, e.g. "GPA: 3.8/4.0\nRelevant Coursework: Data Structures, Algorithms".
- extra_sections: every other section (Accomplishments, Awards, Publications,
  Volunteering, Languages, ...) with its exact title and items verbatim.
- section_order: section keys in the order they appear: "summary", "experience",
  "projects", "skills", "education", "certifications" for those, and the exact title
  for extra sections.
- The LINKS block lists hyperlink targets (anchor text, its line, URL); use it only
  to fill URLs, never as resume content.
""".strip()


async def structure_resume(
    raw_text: str, layout: ResumeLayout | None = None
) -> tuple[ResumeData, str | None]:
    """Use the LLM to structure raw resume text; fall back to heuristics on failure.

    Returns ``(parsed, warning)``; ``warning`` is set when the degraded heuristic
    parser was used, so callers can tell the user instead of failing silently.
    """
    try:
        data = await complete_json(
            _STRUCTURE_SYSTEM,
            f"{SCHEMA_HINT}\n\n{_PARSE_RULES}\n\nRESUME TEXT:\n\"\"\"\n{raw_text}\n\"\"\"",
            temperature=0.0,
            max_tokens=8192,
            purpose="parse",
        )
        if isinstance(data, dict):
            parsed = ResumeData.model_validate(data)
            if layout is not None:
                parsed.layout = layout
            return parsed, None
        reason = "LLM did not return a JSON object"
    except (LlmError, ValueError, TypeError) as exc:
        reason = str(exc)
    log.warning("resume structuring fell back to heuristic parser: %s", reason)
    warning = (
        "AI parsing failed, so a basic text parser was used: experience, projects and "
        f"education may be missing or wrong. Check your LLM keys in Settings. ({reason})"
    )
    parsed = heuristic_parse(raw_text)
    if layout is not None:
        parsed.layout = layout
    return parsed, warning


def heuristic_parse(raw_text: str) -> ResumeData:
    """Minimal best-effort parse used when no LLM is available."""
    email = _EMAIL.search(raw_text)
    phone = _PHONE.search(raw_text)
    linkedin = _LINKEDIN.search(raw_text)
    github = _GITHUB.search(raw_text)

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    name = lines[0] if lines else ""

    contact = ContactInfo(
        name=name,
        email=email.group(0) if email else None,
        phone=phone.group(0).strip() if phone else None,
        linkedin=linkedin.group(0) if linkedin else None,
        github=github.group(0) if github else None,
    )
    # Treat short comma-heavy lines as skill lines.
    skills: list[str] = []
    for ln in lines:
        if "," in ln and len(ln) < 200 and not ln.endswith("."):
            skills.extend(s.strip() for s in ln.split(",") if 1 < len(s.strip()) < 40)
    return ResumeData(
        contact=contact,
        summary=None,
        skills=list(dict.fromkeys(skills))[:40],
    )

