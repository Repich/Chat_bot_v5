from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class AdminAuthorizationResult:
    ok: bool
    status_code: int = 200
    error: str = ""
    message: str = ""


@dataclass(frozen=True)
class AdminSecurityConfig:
    enabled: bool = True
    token: str = ""
    bind_local_only: bool = True
    allowed_config_roots: Sequence[Path] = ()
    allow_raw_query_edit: bool = False

    def authorize(self, *, path: str, headers: Mapping[str, str], client_host: str) -> AdminAuthorizationResult:
        if not path.startswith("/api/admin/"):
            return AdminAuthorizationResult(ok=True)
        if not self.enabled:
            return AdminAuthorizationResult(
                ok=False,
                status_code=403,
                error="admin_disabled",
                message="Admin endpoints are disabled.",
            )
        if self.bind_local_only and not is_loopback_host(client_host):
            return AdminAuthorizationResult(
                ok=False,
                status_code=403,
                error="admin_local_only",
                message="Admin endpoints are available only from localhost.",
            )
        if self.token and not token_matches(headers, self.token):
            return AdminAuthorizationResult(
                ok=False,
                status_code=401,
                error="admin_token_required",
                message="Admin token is required.",
            )
        return AdminAuthorizationResult(ok=True)

    def config_dump_allowed(self, path: Path) -> bool:
        if not self.allowed_config_roots:
            return True
        target = resolve_loose(path)
        for root in self.allowed_config_roots:
            allowed_root = resolve_loose(root)
            if target == allowed_root or allowed_root in target.parents:
                return True
        return False


def token_matches(headers: Mapping[str, str], expected: str) -> bool:
    authorization = header_value(headers, "Authorization")
    if authorization.startswith("Bearer ") and authorization[7:].strip() == expected:
        return True
    return header_value(headers, "X-WIICON5-Admin-Token") == expected


def header_value(headers: Mapping[str, str], name: str) -> str:
    if hasattr(headers, "get"):
        value = headers.get(name, "")
        return str(value or "").strip()
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value or "").strip()
    return ""


def is_loopback_host(value: str) -> bool:
    host = value.strip().lower()
    if host in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_loose(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)
