"""IAM-authenticated MCP client. Google credentials remain at the gateway."""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse


class DataGateway:
    # Mirrors the reviewed data contract and is used to plan requests before
    # the Sheets target sees them. It grants no data access.
    limits = {"max_rows": 100, "max_columns": 4, "max_cells": 400}

    def __call__(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.read(operation, arguments))

    def math(self, operation: str, rows: list[dict[str, Any]], field: str, **options: Any) -> Any:
        return asyncio.run(self.run_math(operation, rows, field, **options))

    async def read(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        if operation not in {"get-metadata", "get-values"}:
            raise ValueError("Unsupported read operation.")
        url = os.environ.get("DATA_GATEWAY_URL") or os.environ["AGENTCORE_GATEWAY_DATAGATEWAY_URL"]
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
                signed = AWSRequest(method=request.method, url=str(request.url),
                                    data=request.content, headers=dict(request.headers))
                SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", region).add_auth(signed)
                request.headers.update(dict(signed.headers))
                yield request

        async with httpx2.AsyncClient(auth=GatewayAuth(), timeout=60, follow_redirects=False) as http:
            async with streamable_http_client(url, http_client=http) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool("SheetsRead___" + operation, arguments)
                    payload = result.model_dump(by_alias=True)
                    if payload.get("isError") or not isinstance(payload.get("structuredContent"), dict):
                        raise ValueError("Gateway rejected the read or returned an invalid result.")
                    return payload["structuredContent"]

    async def run_math(self, operation: str, rows: list[dict[str, Any]], field: str, **options: Any) -> Any:
        """Call the gateway's credential-free MathOps target with retrieved rows."""
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        url = os.environ.get("DATA_GATEWAY_URL") or os.environ["AGENTCORE_GATEWAY_DATAGATEWAY_URL"]
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
                signed = AWSRequest(method=request.method, url=str(request.url), data=request.content, headers=dict(request.headers))
                SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", region).add_auth(signed)
                request.headers.update(dict(signed.headers))
                yield request

        async with httpx2.AsyncClient(auth=GatewayAuth(), timeout=60, follow_redirects=False) as http:
            async with streamable_http_client(url, http_client=http) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool("MathOps___" + operation, {"rows": rows, "field": field, **options})
                    payload = result.model_dump(by_alias=True)
                    content = payload.get("structuredContent")
                    if payload.get("isError") or not isinstance(content, dict) or "value" not in content:
                        raise ValueError("MathOps rejected the calculation or returned an invalid result.")
                    return content["value"]
