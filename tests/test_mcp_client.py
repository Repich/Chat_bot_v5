from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

from wiicon5.mcp.client import HttpMcpClient
from wiicon5.mcp.contracts import McpMetadataRequest, McpQueryRequest


class HttpMcpClientTests(unittest.TestCase):
    def test_http_mcp_client_posts_execute_query_and_metadata_requests(self) -> None:
        calls: List[Dict[str, Any]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                calls.append({"path": self.path, "payload": payload})
                if self.path == "/api/execute_query":
                    body = {"success": True, "data": [{"Код": "001"}]}
                elif self.path == "/api/get_metadata":
                    body = {"success": True, "data": [{"ПолноеИмя": "Справочник.Номенклатура"}], "returned": 1}
                else:
                    body = {"success": False, "error": "unknown path"}
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:
                return None

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            client = HttpMcpClient(base_url=f"http://{host}:{port}")

            query_response = client.execute_query(
                McpQueryRequest(query="ВЫБРАТЬ 1 ГДЕ Код = &Код", params={"Код": "001"}, limit=10, include_schema=True)
            )
            metadata_response = client.get_metadata(McpMetadataRequest(name_mask="Номенклатура"))
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertTrue(query_response.success)
        self.assertEqual(query_response.data[0]["Код"], "001")
        self.assertTrue(metadata_response.success)
        self.assertEqual(metadata_response.returned, 1)
        self.assertEqual(calls[0]["path"], "/api/execute_query")
        self.assertEqual(calls[0]["payload"]["query"], "ВЫБРАТЬ 1 ГДЕ Код = &Код")
        self.assertEqual(calls[0]["payload"]["params"], {"Код": "001"})
        self.assertEqual(calls[1]["path"], "/api/get_metadata")
        self.assertEqual(calls[1]["payload"]["name_mask"], "Номенклатура")
        self.assertEqual(calls[1]["payload"]["limit"], 50)


if __name__ == "__main__":
    unittest.main()
