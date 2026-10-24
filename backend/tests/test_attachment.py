"""Resume attachment resolution: prefer PDF, fall back to DOCX."""

from __future__ import annotations

from app.config import get_settings
from app.routers.outreach import _attachment_for
from app.schemas import SendItem


class _FakeTailoring:
    def __init__(self, id: int, pdf_path: str | None):
        self.id = id
        self.pdf_path = pdf_path


class _FakeDB:
    def __init__(self, tailoring):
        self._t = tailoring

    def get(self, _model, _id):
        return self._t


def test_no_tailoring_id_returns_none():
    assert _attachment_for(_FakeDB(None), SendItem(to_email="a@b.com", subject="s", body="b")) is None


def test_prefers_pdf(tmp_path):
    pdf = tmp_path / "resume_5.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    db = _FakeDB(_FakeTailoring(5, str(pdf)))
    item = SendItem(to_email="a@b.com", subject="s", body="b", tailoring_id=5)
    assert _attachment_for(db, item) == pdf


def test_falls_back_to_docx_when_no_pdf(tmp_path, monkeypatch):
    # pdf_path points to a .tex (Tectonic missing); a .docx exists in output dir.
    out = get_settings().output_path
    docx = out / "resume_7.docx"
    docx.write_bytes(b"PK docx")
    try:
        db = _FakeDB(_FakeTailoring(7, str(out / "resume_7.tex")))
        item = SendItem(to_email="a@b.com", subject="s", body="b", tailoring_id=7)
        assert _attachment_for(db, item) == docx
    finally:
        docx.unlink(missing_ok=True)


def test_none_when_nothing_exists():
    db = _FakeDB(_FakeTailoring(999, None))
    item = SendItem(to_email="a@b.com", subject="s", body="b", tailoring_id=999)
    assert _attachment_for(db, item) is None
