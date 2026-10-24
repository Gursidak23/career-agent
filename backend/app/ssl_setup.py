"""Trust the operating-system certificate store for all outbound TLS.

Many networks (corporate proxies, Zscaler, etc.) terminate TLS with their own
root CA installed in the OS trust store but not in certifi's bundle. Injecting
``truststore`` makes the stdlib ``ssl`` module — and therefore httpx, smtplib,
and the LLM SDKs — use the OS store, so real API calls work without disabling
certificate verification.
"""

from __future__ import annotations

from .logging_setup import get_logger

log = get_logger(__name__)

_DONE = False


def setup_truststore() -> None:
    global _DONE
    if _DONE:
        return
    _DONE = True
    try:
        import truststore

        truststore.inject_into_ssl()
        log.info("truststore: using OS certificate store for TLS verification")
    except Exception as exc:  # noqa: BLE001 - best effort; fall back to certifi
        log.info("truststore unavailable (%s); using default certifi bundle", exc)
