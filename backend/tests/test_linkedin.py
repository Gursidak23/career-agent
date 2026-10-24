import pytest

from app.outreach import linkedin_sender as li
from app.schemas import LinkedInSendItem


# --------------------------------------------------------------------------- #
# profile URL validation (pure)
# --------------------------------------------------------------------------- #
def test_valid_profile_urls():
    assert li.is_valid_profile_url("https://www.linkedin.com/in/jane-doe")
    assert li.is_valid_profile_url("https://linkedin.com/in/jdoe/")
    assert li.is_valid_profile_url("http://in.linkedin.com/in/handle")


def test_invalid_profile_urls():
    assert not li.is_valid_profile_url("https://linkedin.com/company/acme")
    assert not li.is_valid_profile_url("https://example.com/in/jane")
    assert not li.is_valid_profile_url("jane-doe")


# --------------------------------------------------------------------------- #
# dry run validates URLs without launching a browser
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dry_run_grades_urls(monkeypatch):
    # Even if playwright were available, dry_run must not launch it.
    items = [
        LinkedInSendItem(profile_url="https://www.linkedin.com/in/ok", message="hi"),
        LinkedInSendItem(profile_url="https://example.com/in/bad", message="hi"),
    ]
    results = await li.send_batch(items, dry_run=True)
    assert results[0].status == "dry_run"
    assert results[1].status == "failed"
    assert "valid LinkedIn profile" in (results[1].error or "")


# --------------------------------------------------------------------------- #
# send is gated by enabled + availability
# --------------------------------------------------------------------------- #
def _settings_with(*, enabled: bool):
    """A get_settings replacement exposing only the .linkedin section we need."""
    from types import SimpleNamespace

    from app.config import LinkedInSettings

    return lambda: SimpleNamespace(linkedin=LinkedInSettings(enabled=enabled))


@pytest.mark.asyncio
async def test_send_disabled_raises(monkeypatch):
    monkeypatch.setattr(li, "get_settings", _settings_with(enabled=False))
    with pytest.raises(RuntimeError, match="disabled"):
        await li.send_batch(
            [LinkedInSendItem(profile_url="https://www.linkedin.com/in/ok", message="hi")]
        )


@pytest.mark.asyncio
async def test_send_missing_playwright_raises(monkeypatch):
    monkeypatch.setattr(li, "get_settings", _settings_with(enabled=True))
    monkeypatch.setattr(li, "playwright_available", lambda: False)
    with pytest.raises(RuntimeError, match="Playwright is not installed"):
        await li.send_batch(
            [LinkedInSendItem(profile_url="https://www.linkedin.com/in/ok", message="hi")]
        )


# --------------------------------------------------------------------------- #
# API smoke (status endpoint + disabled send guard), no browser
# --------------------------------------------------------------------------- #
def test_linkedin_endpoints_smoke(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    res = client.get("/api/linkedin/status")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"enabled", "playwright_available", "logged_in"}

    # Dry-run send validates without launching a browser.
    res = client.post(
        "/api/linkedin/send",
        json={
            "items": [{"profile_url": "https://www.linkedin.com/in/x", "message": "hi"}],
            "dry_run": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "dry_run"
