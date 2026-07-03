from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from wiicon5.mcp.contracts import McpMetadataRequest, McpMetadataResponse, McpQueryRequest, McpQueryResponse


class McpClient(ABC):
    @abstractmethod
    def execute_query(self, request: McpQueryRequest) -> McpQueryResponse:
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self, request: McpMetadataRequest) -> McpMetadataResponse:
        raise NotImplementedError


class DictMcpClient(McpClient):
    def __init__(self, query_response: Dict[str, Any], metadata_response: Optional[Dict[str, Any]] = None) -> None:
        self.query_response = query_response
        self.metadata_response = metadata_response or {"success": True, "data": []}
        self.query_calls = []
        self.metadata_calls = []

    def execute_query(self, request: McpQueryRequest) -> McpQueryResponse:
        self.query_calls.append(request)
        return McpQueryResponse.from_dict(self.query_response)

    def get_metadata(self, request: McpMetadataRequest) -> McpMetadataResponse:
        self.metadata_calls.append(request)
        return McpMetadataResponse.from_dict(self.metadata_response)


class HttpMcpClient(McpClient):
    def __init__(self, *, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def execute_query(self, request: McpQueryRequest) -> McpQueryResponse:
        return McpQueryResponse.from_dict(self._post_json("/api/execute_query", request.to_dict()))

    def get_metadata(self, request: McpMetadataRequest) -> McpMetadataResponse:
        return McpMetadataResponse.from_dict(self._post_json("/api/get_metadata", request.to_dict()))

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(_drop_empty(payload), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = int(response.status)
                raw_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            raw_body = exc.read().decode("utf-8", errors="replace")
        except OSError as exc:
            return {"success": False, "error": str(exc)}
        try:
            data = json.loads(raw_body)
        except ValueError:
            return {
                "success": False,
                "error": f"MCP returned HTTP {status_code} with non-JSON body",
                "status_code": status_code,
                "body_preview": raw_body[:1000],
            }
        if isinstance(data, dict):
            result = dict(data)
            result.setdefault("status_code", status_code)
            if status_code >= 400 and result.get("success") is not False:
                result = {
                    "success": False,
                    "error": str(result.get("error") or f"MCP returned HTTP {status_code}"),
                    "status_code": status_code,
                    "data": result,
                }
            return result
        if isinstance(data, list):
            return {
                "success": status_code < 400,
                "data": data,
                "count": len(data),
                "returned": len(data),
                "format": "top_level_array",
                "status_code": status_code,
                "error": "" if status_code < 400 else f"MCP returned HTTP {status_code}",
            }
        return {
            "success": False,
            "error": "MCP returned unsupported JSON",
            "status_code": status_code,
            "data": data,
        }


class DisabledMcpClient(McpClient):
    def execute_query(self, request: McpQueryRequest) -> McpQueryResponse:
        return McpQueryResponse(
            success=False,
            error="MCP is disabled.",
            raw={"request": request.to_dict()},
        )

    def get_metadata(self, request: McpMetadataRequest) -> McpMetadataResponse:
        return McpMetadataResponse(
            success=False,
            error="MCP is disabled.",
            raw={"request": request.to_dict()},
        )


def _drop_empty(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [])}
