"""Exercise the actual policy seam; forwarding represents contacting Google."""
import unittest

from gateway.interceptor import intercept
from gateway.tests.test_policy import CONTRACT


def event(operation="get-values", **arguments):
    if operation == "get-metadata":
        arguments = {"ranges": arguments.pop("range", "Performance!A1:B1"), **arguments}
        defaults = {"spreadsheetId": "fixture-sheet"}
    else:
        defaults = {"spreadsheetId": "fixture-sheet", "range": "Performance!A2:B10"}
    return {"interceptorInputVersion": "1.0", "mcp": {"gatewayRequest": {"body": {
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "SheetsRead___" + operation, "arguments": {
            **defaults, **arguments}},
    }}}}


class InterceptorTests(unittest.TestCase):
    def test_rejected_reads_never_forward_to_google(self):
        attempts = [event("update"), event(range="Private!A1:B2"),
                    event(range="Performance!A1:D2"), event(range="Performance!A1:B101"),
                    event(spreadsheetId="other-sheet"), event(range="Performance!A:A"),
                    event(range="Performance!A1:B2,Private!A1:B2"),
                    event(range="Performance!B10:A2"), event(range="Performance!A0:B1"),
                    event(range=None), event(fields="*"), event(includeGridData=True),
                    event("get-metadata", range="Performance!A1:B2")]
        for request in attempts:
            with self.subTest(request=request):
                result = intercept(request, CONTRACT)["mcp"]
                self.assertNotIn("transformedGatewayRequest", result)
                self.assertTrue(result["transformedGatewayResponse"]["body"]["result"]["isError"])

    def test_accepted_read_forwards_only_fixed_safe_google_parameters(self):
        result = intercept(event(), CONTRACT)["mcp"]["transformedGatewayRequest"]["body"]
        self.assertEqual({"spreadsheetId": "fixture-sheet", "range": "'Performance'!A2:B10",
                          "majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
                         result["params"]["arguments"])

    def test_metadata_is_limited_to_approved_headers(self):
        result = intercept(event("get-metadata", range="Performance!A1:B1"), CONTRACT)
        arguments = result["mcp"]["transformedGatewayRequest"]["body"]["params"]["arguments"]
        self.assertEqual("'Performance'!A1:B1", arguments["ranges"])
        self.assertEqual("sheets(data(startColumn,startRow,rowData(values(formattedValue))))",
                         arguments["fields"])
        self.assertNotIn("range", arguments)


if __name__ == "__main__":
    unittest.main()
