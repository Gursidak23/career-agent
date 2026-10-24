"""Recruiter email discovery.

A provider chain (site crawler -> pattern+verify -> Apify -> AgentQL) that
resolves a company domain, aggregates and de-dupes candidates, verifies them,
and returns a ranked list. Keyless providers work with no configuration.
"""

from .base import EmailCandidate, EmailFinder
from .service import EmailFinderService, available_providers, get_service

__all__ = [
    "EmailCandidate",
    "EmailFinder",
    "EmailFinderService",
    "available_providers",
    "get_service",
]
