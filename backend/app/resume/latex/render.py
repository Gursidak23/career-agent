"""Render ResumeData to an ATS-clean LaTeX document and compile to PDF.

Uses Jinja2 with LaTeX-friendly delimiters (so braces in the template don't
clash). PDF compilation shells out to Tectonic; if Tectonic is not installed,
we still return the .tex source and report that the PDF is unavailable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ...config import get_settings
from ...schemas import ResumeData

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_SPECIAL = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


def latex_escape(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    # Escape backslash first to avoid double-processing replacements.
    out = []
    for ch in text:
        out.append(_SPECIAL.get(ch, ch))
    return "".join(out)


def full_url(value: str) -> str:
    v = value.strip()
    return v if re.match(r"^[a-z]+:", v) else f"https://{v}"


def display_url(value: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", value.strip()).rstrip("/")


def tex_url(value: str) -> str:
    # Inside \href only these two need escaping.
    return value.replace("\\", "/").replace("#", r"\#").replace("%", r"\%")


def link_label(url: str) -> str:
    return "GitHub" if "github.com" in url.lower() else "Link"


def labelled(text: str) -> str:
    """'Hackathon Lead, CodeFest 2.0: Led ...' -> bold label, plain rest."""
    label, sep, rest = text.partition(":")
    if sep and 0 < len(label) <= 60 and rest.strip() and "http" not in label:
        return rf"\textbf{{{latex_escape(label)}:}} {latex_escape(rest.strip())}"
    return latex_escape(text)


def short_detail(line: str) -> bool:
    """Short education details (grade) sit inline; longer ones get their own line."""
    return len(line) <= 30 and not line.lower().startswith("relevant")


def contact_links(resume: ResumeData) -> list[tuple[str, str]]:
    """(url, display text) for LinkedIn, GitHub and website, accepting bare handles."""
    c = resume.contact
    out: list[tuple[str, str]] = []
    for value, site in ((c.linkedin, "linkedin.com/in/"), (c.github, "github.com/"), (c.website, "")):
        if not value:
            continue
        v = value.strip()
        if site and site.split("/")[0] not in v.lower():
            v = site + v.lstrip("@/")
        out.append((full_url(v), display_url(v)))
    return out


# Spacing presets, loosest first. Level 0 matches a classic 10pt one-page resume;
# later levels tighten until the output fits the original page count.
DENSITY = [
    {"font": "10pt", "leading": "11pt", "margin_x": "0.5in", "margin_y": "0.3in",
     "itemsep": "0pt", "section_gap": "2pt", "entry_gap": "2pt"},
    {"font": "9.75pt", "leading": "10.75pt", "margin_x": "0.45in", "margin_y": "0.3in",
     "itemsep": "0pt", "section_gap": "1pt", "entry_gap": "1pt"},
    {"font": "9.5pt", "leading": "10.4pt", "margin_x": "0.42in", "margin_y": "0.28in",
     "itemsep": "-1pt", "section_gap": "0pt", "entry_gap": "0pt"},
    {"font": "9pt", "leading": "10pt", "margin_x": "0.4in", "margin_y": "0.25in",
     "itemsep": "-1pt", "section_gap": "0pt", "entry_gap": "0pt"},
]


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((#",
        comment_end_string="#))",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
    )
    env.filters["tex"] = latex_escape
    env.filters["texurl"] = tex_url
    env.filters["fullurl"] = full_url
    env.filters["displayurl"] = display_url
    env.filters["linklabel"] = link_label
    env.filters["labelled"] = labelled
    env.tests["shortdetail"] = short_detail
    return env


def render_tex(resume: ResumeData, *, template: str = "ats_clean.tex.j2", density: int = 0) -> str:
    env = _env()
    tmpl = env.get_template(template)
    d = DENSITY[max(0, min(density, len(DENSITY) - 1))]
    return tmpl.render(r=resume, d=d, contact_links=contact_links(resume))


def tectonic_available() -> bool:
    binary = get_settings().tectonic_bin
    return shutil.which(binary) is not None


@dataclass
class RenderResult:
    tex_path: Path
    pdf_path: Path | None
    pdf_available: bool
    message: str = ""


def _compile(tex_source: str, stem: str) -> tuple[bytes | None, str]:
    """Compile with Tectonic; (pdf bytes, "") on success or (None, error)."""
    binary = get_settings().tectonic_bin
    with tempfile.TemporaryDirectory() as tmp:
        tmp_tex = Path(tmp) / f"{stem}.tex"
        tmp_tex.write_text(tex_source, encoding="utf-8")
        try:
            proc = subprocess.run(
                [binary, tmp_tex.name, "--outdir", tmp],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=180,  # first run downloads the TeX bundle
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"Tectonic failed to run: {exc}"
        produced = Path(tmp) / f"{stem}.pdf"
        if proc.returncode != 0 or not produced.exists():
            return None, f"Tectonic compile error: {proc.stderr[-800:] or proc.stdout[-800:]}"
        return produced.read_bytes(), ""


def _page_count(pdf: bytes) -> int:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return len(doc)


def render_pdf(resume: ResumeData, out_dir: Path, stem: str) -> RenderResult:
    """Render to .tex and, with Tectonic, to a PDF no longer than the original.

    Starts at the classic spacing and tightens one density level at a time until
    the page count fits the uploaded resume's (when known).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / f"{stem}.tex"
    target = resume.layout.pages

    if not tectonic_available():
        tex_path.write_text(render_tex(resume), encoding="utf-8")
        return RenderResult(
            tex_path=tex_path,
            pdf_path=None,
            pdf_available=False,
            message=(
                "Tectonic is not installed; returned LaTeX source only. "
                "Install from https://tectonic-typesetting.github.io to enable PDF output."
            ),
        )

    pdf, message, pages = None, "", 0
    for level in range(len(DENSITY) if target else 1):
        tex_source = render_tex(resume, density=level)
        pdf, message = _compile(tex_source, stem)
        if pdf is None:
            break
        pages = _page_count(pdf)
        if not target or pages <= target:
            break
    tex_path.write_text(tex_source, encoding="utf-8")
    if pdf is None:
        return RenderResult(tex_path, None, False, message)
    pdf_path = out_dir / f"{stem}.pdf"
    pdf_path.write_bytes(pdf)
    note = f" ({pages} pages; the original had {target})" if target and pages > target else ""
    return RenderResult(tex_path, pdf_path, True, f"PDF generated.{note}")
