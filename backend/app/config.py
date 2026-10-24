"""Environment-overridable configuration.

All settings live under the ``CAREER_`` prefix; nested values use a double
underscore delimiter, e.g. ``CAREER_LLM__GEMINI_API_KEY=...`` or
``CAREER_SMTP__HOST=smtp.gmail.com``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseModel):
    """LLM provider config. Providers are tried in a fixed fallback order:
    gemini -> groq -> copilot. A provider is simply skipped if its credential
    is missing."""

    gemini_api_key: str | None = None
    # Rolling alias: pinned versions get retired for new keys (2.5-flash did).
    # Flash-Lite answers in ~2s vs 60-100s+ for Flash (its long "thinking"), and
    # the tailoring loop's best-of-N scoring makes up for the smaller model.
    gemini_model: str = "gemini-flash-lite-latest"

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # GitHub Copilot (fine-grained PAT with the "Copilot Requests" permission).
    # Paid per call in Copilot AI credits, so it is the last resort.
    copilot_github_token: str | None = None
    copilot_model: str | None = None  # None = the account's default model
    copilot_timeout_seconds: float = 180.0

    temperature: float = 0.2
    max_output_tokens: int = 4096
    max_retries: int = 3
    request_timeout_seconds: float = 60.0

    # Stay inside free-tier quotas (shared token bucket across all calls).
    rate_per_minute: int = 25
    # Response caching for identical prompts.
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86_400
    cache_persist: bool = True
    # Number of candidates generated per tailoring round (best-of-N).
    tailor_candidates: int = 2


class EmailFinderSettings(BaseModel):
    """Recruiter email discovery. Keyless providers (crawler, pattern+verify)
    work with no config; Apify/AgentQL activate when their key is set."""

    # Keyless providers
    crawler_enabled: bool = True
    pattern_enabled: bool = True
    crawler_max_pages: int = 6

    # Verification
    smtp_verify: bool = True
    verify_from_email: str = "verify@example.com"

    # Keyed providers (free tiers; dormant until a key is provided)
    apify_token: str | None = None
    apify_actor: str = "lukaskrivka/article-extractor-smart"
    agentql_api_key: str | None = None
    agentql_endpoint: str = "https://api.agentql.com/v1/query-data"

    # Behavior
    timeout_seconds: float = 20.0
    stop_on_verified: bool = True
    auto_enrich: bool = False
    max_candidates: int = 10


class ScraperSettings(BaseModel):
    """Job-source config. The default job boards are real and keyless. The Apify
    'New Job Posts Finder' source (Indian boards: Naukri/Foundit/Hirist/Indeed/
    Internshala/LinkedIn) activates when an Apify token is set, and an external
    Scrapy project can be wired in for custom boards."""

    # External Scrapy project (optional; see scraper/scrapy_source.py).
    project_dir: str = ""
    spider: str = ""

    # Apify-backed Indian job boards (free-tier; dormant until a token is set).
    apify_token: str | None = None
    apify_jobs_actor: str = "spartany/new-job-posts-finder"
    apify_location: str = "India"
    apify_mode: str = "deduplicated"
    apify_timeout_seconds: float = 120.0


class LinkedInSettings(BaseModel):
    """LinkedIn DM automation via Playwright with a persistent login session.

    Off by default (it drives a real browser against your own account). Log in
    once via the /api/linkedin/login flow; the session is stored in
    ``user_data_dir`` and reused for subsequent sends.
    """

    enabled: bool = False
    headless: bool = True
    user_data_dir: str = "./data/linkedin_profile"
    # Browser channel to reuse (e.g. "chrome", "msedge"); blank = bundled Chromium.
    browser_channel: str = ""
    # Human-like pacing to reduce automation-detection / spam risk.
    per_minute: int = 5
    min_delay_seconds: float = 4.0
    timeout_seconds: float = 45.0


class SmtpSettings(BaseModel):
    host: str = "smtp.gmail.com"
    port: int = 587
    username: str | None = None
    password: str | None = None
    from_name: str | None = None
    use_tls: bool = True
    # Throttle outgoing mail to avoid provider limits / spam flags.
    per_minute: int = 20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAREER_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Career Agent"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    db_url: str = "sqlite:///./career_agent.db"
    data_dir: str = "./data"
    tectonic_bin: str = "tectonic"

    llm: LlmSettings = Field(default_factory=LlmSettings)
    smtp: SmtpSettings = Field(default_factory=SmtpSettings)
    emailfinder: EmailFinderSettings = Field(default_factory=EmailFinderSettings)
    scraper: ScraperSettings = Field(default_factory=ScraperSettings)
    linkedin: LinkedInSettings = Field(default_factory=LinkedInSettings)

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_path(self) -> Path:
        p = self.data_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def output_path(self) -> Path:
        p = self.data_path / "output"
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


def shadowed_env_vars(env_file: str = ".env") -> list[str]:
    """CAREER_* variables set in the process environment with a different value than .env.

    The process environment wins over .env, so a shell that exported an older
    .env (e.g. an IDE terminal) silently keeps stale keys and models.
    """
    from dotenv import dotenv_values

    if not Path(env_file).exists():
        return []
    file_values = dotenv_values(env_file)
    return sorted(
        key
        for key, value in file_values.items()
        if key.startswith("CAREER_")
        and key in os.environ
        and os.environ[key].strip() != (value or "").strip()
    )

