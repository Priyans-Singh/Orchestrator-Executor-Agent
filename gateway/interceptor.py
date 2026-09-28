"""AgentCore REQUEST interceptor: no Google credentials or network access."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from gateway.policy import PolicyDenied, SheetsPolicy


METADATA_FIELDS = "sheets(data(startColumn,startRow,rowData(values(formattedValue))))"


def intercept(event: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    try:
        if event.get("interceptorInputVersion") != "1.0":
            raise PolicyDenied("Unsupported interceptor version.")
        body = event["mcp"]["gatewayRequest"]["body"]
        if not isinstance(body, dict):
            raise PolicyDenied("A single MCP request is required.")
        method = body.get("method")
        if method in {"initialize", "notifications/initialized", "ping", "tools/list"}:
            return {"interceptorOutputVersion": "1.0", "mcp": {
                "transformedGatewayRequest": {"body": body}}}
        if method != "tools/call":
            raise PolicyDenied("Unsupported MCP method.")
        params = body["params"]
        name = params["name"]
        if name not in {"SheetsRead___get-values", "SheetsRead___get-metadata"}:
            raise PolicyDenied("Tool is not approved.")
        operation = name.removeprefix("SheetsRead___")
        arguments = dict(params["arguments"])
        if operation == "get-metadata":
            if "range" in arguments:
                raise PolicyDenied("Metadata uses ranges, not range.")
            arguments["range"] = arguments.pop("ranges")
        approved = SheetsPolicy(contract).authorize(operation, arguments)
        safe_arguments = {"spreadsheetId": approved["spreadsheet_id"]}
        if operation == "get-metadata":
            safe_arguments.update(ranges=approved["range"], fields=METADATA_FIELDS)
        else:
            safe_arguments.update(range=approved["range"], majorDimension="ROWS",
                                  valueRenderOption="UNFORMATTED_VALUE")
        forwarded = deepcopy(body)
        forwarded["params"] = {"name": name, "arguments": safe_arguments}
        return {"interceptorOutputVersion": "1.0", "mcp": {
            "transformedGatewayRequest": {"body": forwarded}}}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"interceptorOutputVersion": "1.0", "mcp": {
            "transformedGatewayResponse": {"statusCode": 200, "body": {
                "jsonrpc": "2.0", "id": body.get("id") if isinstance(body, dict) else None,
                "result": {"isError": True, "content": [{"type": "text",
                    "text": "Read rejected by the data contract."}]}}}}}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # Package the reviewed contract with this Lambda; callers cannot select it.
    with (Path(__file__).parent / "data-contract.yaml").open() as source:
        contract = json.load(source)
    if "gatewayResponse" in event.get("mcp", {}):
        return annotate_response(event, contract)
    return intercept(event, contract)


def annotate_response(event: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    """Attach authoritative contract semantics to successful Sheets responses."""
    checked = intercept(event, contract)
    if "transformedGatewayResponse" in checked["mcp"]:
        return checked
    request = event["mcp"]["gatewayRequest"]["body"]
    response = deepcopy(event["mcp"]["gatewayResponse"])
    if request.get("method") != "tools/call":
        return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayResponse": response}}
    result = response["body"].get("result")
    if not isinstance(result, dict) or result.get("isError"):
        return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayResponse": response}}
    import json

    data = result.get("structuredContent")
    if data is None:
        blocks = result.get("content", [])
        if len(blocks) != 1 or blocks[0].get("type") != "text":
            raise ValueError("Expected one JSON Sheets response.")
        data = json.loads(blocks[0]["text"])
    params = request["params"]
    operation = params["name"].removeprefix("SheetsRead___")
    arguments = dict(params["arguments"])
    if operation == "get-metadata":
        arguments["range"] = arguments.pop("ranges")
    approved = SheetsPolicy(contract).authorize(operation, arguments)
    annotated = {**approved, "operation": operation, "data": data}
    if operation == "get-metadata":
        annotated["header_mappings"] = _header_mappings(data, approved)
        annotated["fields"] = {column: semantic for column, semantic in approved["fields"].items()
                               if column in annotated["header_mappings"]}
    response["body"]["result"] = {"isError": False, "structuredContent": annotated,
                                    "content": [{"type": "text", "text": json.dumps(annotated)}]}
    return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayResponse": response}}


def _header_mappings(data: Any, approved: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Map only contract-listed headers; unknown headers never become semantics."""
    mappings: dict[str, dict[str, Any]] = {}
    try:
        grid = data["sheets"][0]["data"][0]
        start = int(grid.get("startColumn", 0))
        headers = grid["rowData"][0]["values"]
    except (KeyError, IndexError, TypeError, ValueError):
        return mappings
    for offset, cell in enumerate(headers):
        header = cell.get("formattedValue") if isinstance(cell, Mapping) else None
        column = _column_name(start + offset + 1)
        semantic = approved["fields"].get(column)
        default_aliases = [semantic.replace("_", " ").title()] if semantic is not None else []
        aliases = approved["header_aliases"].get(semantic, default_aliases)
        if not isinstance(header, str) or semantic is None or header not in aliases:
            continue
        mappings[column] = {"header": header, "semantic": semantic,
                            "is_alias": header != aliases[0]}
    return mappings


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result
