"""Diagnostic analyst transport configuration."""
from specialist_a2a import SpecialistA2AAdapter


class DiagnosticA2AAdapter(SpecialistA2AAdapter):
    url_environment = "DIAGNOSTIC_AGENT_URL"
    jwt_environment = "DIAGNOSTIC_AGENT_JWT"
    envelope_name = "diagnostic-envelope"
