"""Evidence Guard transport configuration."""
from specialist_a2a import SpecialistA2AAdapter


class EvidenceA2AAdapter(SpecialistA2AAdapter):
    url_environment = "EVIDENCE_AGENT_URL"
    jwt_environment = "EVIDENCE_AGENT_JWT"
    envelope_name = "evidence-envelope"
