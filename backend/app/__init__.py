"""Career Agent backend: Resume ATS Optimizer + Recruiter Outreach."""

from .ssl_setup import setup_truststore

# Trust the OS certificate store as early as possible so every outbound TLS call
# (job sources, email finder, LLM SDKs, SMTP) works behind TLS-intercepting proxies.
setup_truststore()

__version__ = "0.1.0"
