from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from wiicon5.mcp.client import McpClient
from wiicon5.mcp.contracts import McpQueryRequest, normalize_mcp_rows
from wiicon5.workbench.audit import compact_payload, utc_now
from wiicon5.workbench.models import HumanSkillDraft
from wiicon5.workbench.preview import QueryPreviewResult, QueryPreviewService
from wiicon5.workbench.store import atomic_write_text


@dataclass(frozen=True)
class SmokeTestResult:
    smoke_id: str
    draft_id: str
    ok: bool
    preview: QueryPreviewResult
    row_count: int = 0
    rows_sample: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "smoke_id": self.smoke_id,
            "draft_id": self.draft_id,
            "ok": self.ok,
            "preview": self.preview.to_dict(),
            "row_count": self.row_count,
            "rows_sample": compact_payload({"rows": self.rows_sample}).get("rows", []),
            "error": self.error,
            "path": self.path,
        }


class McpSmokeTestService:
    def __init__(
        self,
        *,
        bot_instance_root: Path,
        mcp_client: McpClient,
        preview_service: Optional[QueryPreviewService] = None,
        max_rows: int = 10,
    ) -> None:
        self.bot_instance_root = bot_instance_root
        self.mcp_client = mcp_client
        self.preview_service = preview_service or QueryPreviewService()
        self.max_rows = max(1, min(max_rows, 50))
        self.smoke_root = bot_instance_root / "workbench" / "smoke"

    def run(self, draft: HumanSkillDraft) -> SmokeTestResult:
        smoke_id = "smoke_" + uuid4().hex[:12]
        preview = self.preview_service.preview(draft)
        if not preview.ok:
            result = SmokeTestResult(
                smoke_id=smoke_id,
                draft_id=draft.draft_id,
                ok=False,
                preview=preview,
                error="Query preview failed; MCP smoke was not executed.",
            )
            return self._persist(draft, result)
        response = self.mcp_client.execute_query(
            McpQueryRequest(
                query=preview.query,
                params=preview.params,
                limit=min(preview.limit, self.max_rows),
                include_schema=True,
            )
        )
        rows = normalize_mcp_rows(response)
        result = SmokeTestResult(
            smoke_id=smoke_id,
            draft_id=draft.draft_id,
            ok=response.success,
            preview=preview,
            row_count=len(rows),
            rows_sample=rows[: self.max_rows],
            error=response.error,
        )
        return self._persist(draft, result)

    def _persist(self, draft: HumanSkillDraft, result: SmokeTestResult) -> SmokeTestResult:
        draft_id = draft.draft_id or "unknown_draft"
        path = self.smoke_root / draft_id / f"{result.smoke_id}.json"
        payload = {
            "ts": utc_now(),
            "result": result.to_dict(),
        }
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return SmokeTestResult(
            smoke_id=result.smoke_id,
            draft_id=result.draft_id,
            ok=result.ok,
            preview=result.preview,
            row_count=result.row_count,
            rows_sample=list(result.rows_sample),
            error=result.error,
            path=str(path),
        )
