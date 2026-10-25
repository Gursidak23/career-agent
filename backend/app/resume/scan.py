"""Recruiter 6-second scan: where a skimming recruiter's eyes likely land.

A transparent heuristic, not a trained eye-tracking model. Recruiter eye-tracking
studies (e.g. Ladders, 2018) describe a ~7 second first pass in an F-shaped
pattern: down the left edge, drawn to the name, titles, companies, dates, bold
text and numbers. Here every text run on page 1 gets an attention weight from
its position (top/left first), emphasis (bold, larger, italic titles), line
starts and digits. In 6 seconds a skimmer makes ~24 fixations, taking in about
90 words, so the highest-attention runs up to that budget form the "seen zone".
The report says which target keywords and metrics fall inside it, and the
heatmap shows the gradient.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from ..schemas import ResumeData, ScanReport
from .ats import CANONICAL, mentions, score_resume
from .roles import get_role

SEEN_WORD_BUDGET = 90
_DIGIT = re.compile(r"\d")


@dataclass
class _Run:
    text: str
    rect: tuple[float, float, float, float]
    attention: float = 0.0
    seen: bool = False


def _runs(page) -> list[_Run]:
    """Text runs (spans) with an attention weight each."""
    height, width = page.rect.height, page.rect.width
    data = page.get_text("dict")
    sizes = [s["size"] for b in data["blocks"] for line in b.get("lines", []) for s in line["spans"] if s["text"].strip()]
    body = sorted(sizes)[len(sizes) // 2] if sizes else 10.0
    runs: list[_Run] = []
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for i, span in enumerate(line["spans"]):
                text = span["text"].strip()
                if not text:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                vertical = math.exp(-2.2 * (y0 / height))
                horizontal = 1 - 0.5 * (x0 / width)
                bold = bool(span["flags"] & 16) or "bold" in span["font"].lower()
                italic = bool(span["flags"] & 2) or "italic" in span["font"].lower()
                emphasis = (1.6 if bold else 1.0) * (1.4 if span["size"] > body * 1.15 else 1.0)
                emphasis *= 1.15 if italic else 1.0
                emphasis *= 1.2 if _DIGIT.search(text) else 1.0
                emphasis *= 1.25 if i == 0 else 1.0  # eyes run down line starts
                runs.append(_Run(text, (x0, y0, x1, y1), vertical * horizontal * emphasis))
    top = max((r.attention for r in runs), default=1.0) or 1.0
    for r in runs:
        r.attention /= top
    budget = SEEN_WORD_BUDGET
    for r in sorted(runs, key=lambda r: r.attention, reverse=True):
        if budget <= 0:
            break
        r.seen = True
        budget -= len(r.text.split())
    return runs


def _heatmap_png(doc, runs: list[_Run]) -> bytes:
    page = doc[0]
    for r in runs:
        a = r.attention
        # Hot (red) -> warm (amber) -> cool (faint yellow) by attention.
        color = (1.0, max(0.0, 1.0 - 1.2 * a), 0.1 if a > 0.5 else 0.3)
        page.draw_rect(r.rect, color=None, fill=color, fill_opacity=min(0.55, 0.08 + 0.6 * a), overlay=True)
        if r.seen:
            page.draw_rect(r.rect, color=(0.85, 0.1, 0.1), width=0.6, overlay=True)
    return page.get_pixmap(dpi=110).tobytes("png")


def scan_pdf(pdf_path: Path, resume: ResumeData, role: str, job_description: str | None) -> tuple[ScanReport, bytes]:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        runs = _runs(doc[0])
        png = _heatmap_png(doc, runs)

    seen_text = " ".join(r.text for r in sorted((r for r in runs if r.seen), key=lambda r: (r.rect[1], r.rect[0])))
    seen_lower = seen_text.lower()
    all_lower = " ".join(r.text for r in runs).lower()

    report = score_resume(resume, role, job_description)
    keywords = report.matched_keywords  # ones the resume has, in target priority order
    in_view = [CANONICAL.get(k, k) for k in keywords if mentions(k, seen_lower)]
    buried = [CANONICAL.get(k, k) for k in keywords if not mentions(k, seen_lower) and mentions(k, all_lower)]

    metric_runs = [r for r in runs if _DIGIT.search(r.text) and not re.search(r"\b(19|20)\d{2}\b|\+?\d[\d -]{7,}", r.text)]
    metrics_seen = sum(1 for r in metric_runs if r.seen)

    tips: list[str] = []
    label = get_role(role).label
    headline = (resume.contact.headline or "").lower()
    if headline and not all(w in headline for w in label.lower().split()):
        tips.append(f"Your headline doesn't say \"{label}\". It's the first thing read; consider leading with the target title.")
    if buried:
        tips.append(
            "Key skills sit outside the first-glance zone: "
            + ", ".join(buried[:5])
            + ". Surface the true ones in your summary or first bullets."
        )
    if resume.experience and resume.experience[0].bullets and not _DIGIT.search(resume.experience[0].bullets[0]):
        tips.append(f"Your first {resume.experience[0].company} bullet has no number; lead with your strongest metric.")
    if resume.summary and len(resume.summary.split()) > 60:
        tips.append("Your summary is long and fills the most-read part of the page; aim for 2 lines.")
    if metric_runs and metrics_seen == 0:
        tips.append("None of your numbers land in the first-glance zone.")

    return (
        ScanReport(
            seen_words=sum(len(r.text.split()) for r in runs if r.seen),
            seen_text=seen_text,
            keywords_in_view=in_view,
            keywords_buried=buried,
            metrics_in_view=metrics_seen,
            metrics_total=len(metric_runs),
            tips=tips,
        ),
        png,
    )
