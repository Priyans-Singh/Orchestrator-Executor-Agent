"""IAM-authenticated client for the Gateway-managed Web Search connector."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlparse


class EvidenceGateway:
    def __call__(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return asyncio.run(self.search(query, filters))

    async def search(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        url = os.environ.get("EVIDENCE_GATEWAY_URL") or os.environ["AGENTCORE_GATEWAY_EVIDENCEGATEWAY_URL"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("An HTTPS gateway URL is required.")
        session = boto3.Session()
        region = os.environ.get("AWS_REGION") or session.region_name
        if not region:
            raise ValueError("AWS region is required.")

        class GatewayAuth(httpx2.Auth):
            requires_request_body = True

            def auth_flow(self, request):
                credentials = session.get_credentials()
                if credentials is None:
                    raise ValueError("Gateway IAM credentials are unavailable.")
                signed = AWSRequest(method=request.method, url=str(request.url), data=request.content,
                                    headers=dict(request.headers))
                SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", region).add_auth(signed)
                request.headers.update(dict(signed.headers))
                yield request

        arguments: dict[str, Any] = {"query": query}
        if filters is not None:
            arguments["filters"] = filters
        async with httpx2.AsyncClient(auth=GatewayAuth(), timeout=60, follow_redirects=False) as http:
            async with streamable_http_client(url, http_client=http) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool("WebSearch", arguments)
                    payload = result.model_dump(by_alias=True)
                    if payload.get("isError"):
                        raise ValueError("Gateway rejected the search or returned invalid results.")
                    content = payload.get("content")
                    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
                        raise ValueError("Gateway response has no text content.")
                    encoded = content[0].get("text")
                    try:
                        decoded = json.loads(encoded)
                    except (TypeError, json.JSONDecodeError) as error:
                        raise ValueError("Gateway response content is not JSON.") from error
                    results = decoded.get("results") if isinstance(decoded, dict) else None
                    if not isinstance(results, list):
                        raise ValueError("Gateway response has no results array.")
                    return results
