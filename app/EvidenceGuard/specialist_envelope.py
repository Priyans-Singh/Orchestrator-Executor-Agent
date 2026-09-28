"""Schema-valid Evidence Guard envelopes at the specialist A2A seam."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from evidence_policy import domain_policy


def build_evidence_envelope(
    request: Mapping[str, Any], search: Callable[..., Any] | None = None, *, retrieved_at: str | None = None
) -> dict[str, Any]:
    """Search twice through the gateway and return citations or standalone context.

    Reputation is assigned solely by the gateway pass that returned a result.
    """
    try:
        query, finding_ids = _normalize_request(request)
        if search is None:
            raise ValueError("No Evidence Gateway is configured.")
        denylist, trusted_domains = domain_policy()
        # Always make both calls, including when either pass fails.
        general_error = trusted_error = None
        try:
            general = search(query, filters=None)
        except Exception as error:
            general_error = error
            general = []
        try:
            trusted = search(query, filters={"domainFilter": {"include": trusted_domains}})
        except Exception as error:
            trusted_error = error
            trusted = []
        if general_error or trusted_error:
            raise ValueError("One or more Evidence Gateway searches failed.")
        results = _merge_results(general, trusted, denylist)
        timestamp = retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        items = [_provenance(result, tier, query, timestamp) for result, tier in results]
    except (OSError, TypeError, ValueError, KeyError):
        return failed_evidence_envelope("The Evidence Gateway search could not be completed.")

    if finding_ids:
        for item in items:
            item["corroborates_finding_id"] = finding_ids
            item["challenges_finding_id"] = []
        return {"status": "complete", "citations": items, "clarifying_questions": [], "narrative": None}
    return {"status": "complete", "context_snippets": items, "clarifying_questions": [], "narrative": None}


def _normalize_request(request: Mapping[str, Any]) -> tuple[str, list[str]]:
    if not isinstance(request, Mapping):
        raise ValueError("Delegation request must be a JSON object.")
    for field in ("task_id", "context_id", "objective"):
        if not isinstance(request.get(field), str) or not request[field].strip():
            raise ValueError(f"Delegation request requires a non-empty {field}.")
    scope = request.get("scope")
    if not isinstance(scope, Mapping):
        raise ValueError("Delegation request requires a scope object.")
    query = scope.get("query")
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
        raise ValueError("scope.query must be a non-empty string of at most 200 characters.")
    findings = scope.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("scope.findings must be an array.")
    finding_ids = []
    for finding in findings:
        if not isinstance(finding, Mapping) or not isinstance(finding.get("id"), str) or not finding["id"].strip():
            raise ValueError("Every finding requires a non-empty id.")
        finding_ids.append(finding["id"].strip())
    return query.strip(), list(dict.fromkeys(finding_ids))


def _search_results(response: Any) -> list[Mapping[str, Any]]:
    if isinstance(response, Mapping):
        response = response.get("results")
    if not isinstance(response, list) or not all(isinstance(item, Mapping) for item in response):
        raise ValueError("Evidence Gateway returned invalid search results.")
    return response


def _merge_results(general: Any, trusted: Any, denylist: set[str]) -> list[tuple[Mapping[str, Any], str]]:
    merged: dict[str, tuple[Mapping[str, Any], str]] = {}
    for result in _search_results(general):
        url = _url(result)
        if _is_denylisted(url, denylist):
            continue
        merged[url] = (result, "general")
    for result in _search_results(trusted):
        url = _url(result)
        if _is_denylisted(url, denylist):
            continue
        merged[url] = (result, "trusted")
    return list(merged.values())


def _url(result: Mapping[str, Any]) -> str:
    url = result.get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not isinstance(url, str) or not parsed or parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Gateway result requires an HTTPS URL.")
    return url


def _is_denylisted(url: str, denylist: set[str]) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == domain or hostname.endswith("." + domain) for domain in denylist)


def _provenance(result: Mapping[str, Any], tier: str, query: str, retrieved_at: str) -> dict[str, Any]:
    url = _url(result)
    title = result.get("title")
    snippet = result.get("snippet", result.get("text"))
    published_date = result.get("publishedDate")
    if not isinstance(title, str) or not title.strip() or not isinstance(snippet, str) or not snippet.strip():
        raise ValueError("Gateway result requires title and snippet.")
    if published_date is not None and not isinstance(published_date, str):
        raise ValueError("Gateway result publishedDate must be a string or null.")
    return {"url": url, "title": title.strip(), "publishedDate": published_date,
            "snippet": snippet.strip(), "reputation_tier": tier, "retrieved_at": retrieved_at, "query": query}


def failed_evidence_envelope(message: str) -> dict[str, Any]:
    """Build a schema-valid failure response without implementation details."""
    return {"status": "failed", "citations": [], "clarifying_questions": [], "narrative": message}
