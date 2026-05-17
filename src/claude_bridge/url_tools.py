"""URL-fetch tool for Nulm – security-constrained HTTP reader."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import hashlib
import http.client
import ipaddress
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from claude_bridge.tool_utils import json_response

_MAX_SIZE = 1024 * 1024  # 1 MB
_MAX_REDIRECTS = 5
_TIMEOUT_SECONDS = 10
_RESPONSE_TRUNCATION = 100 * 1024  # 100 KB
_IP_LIKE_RE = re.compile(r"^[0-9a-fA-FxX.:]+$")
_INVALID_HOSTNAME_CHARS_RE = re.compile(r"[\s\x00-\x1f\x7f<>\"\'\\|]")
_PATH_TRAVERSAL_RE = re.compile(r"(^|/)\.\.(/|$)")
_IDN_RE = re.compile(r"xn--[a-z0-9]+", re.IGNORECASE)


def _is_private_host(host: str) -> bool:
    """Return True if *host* is an internal/private address that must be blocked."""
    if not host:
        return True
    host_lower = host.lower()
    if host_lower in ("localhost", "0.0.0.0", "local"):
        return True
    if host_lower.endswith(".local"):
        return True

    ip = None
    try:
        ip = ipaddress.ip_address(host_lower)
    except ValueError:
        try:
            ip = ipaddress.IPv4Address(host_lower)
        except ValueError:
            if _IP_LIKE_RE.match(host_lower):
                return True
            return False

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified:
        return True
    return False


def _is_internationalized_domain(hostname: str) -> bool:
    if not hostname:
        return False
    return bool(_IDN_RE.search(hostname)) or any(ord(c) > 127 for c in hostname)


def _has_path_traversal(path: str) -> bool:
    if not path:
        return False
    return bool(_PATH_TRAVERSAL_RE.search(path))


def _validate_url_syntax(url: str) -> tuple[bool, str]:
    if not url or not url.strip():
        return False, "URL cannot be empty"
    parsed = urlparse(url)
    scheme = parsed.scheme
    if scheme not in ("http", "https"):
        return False, f"Unsupported scheme: {scheme or '(none)'}"
    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"
    if _INVALID_HOSTNAME_CHARS_RE.search(hostname):
        return False, f"Invalid characters in hostname: {hostname}"
    path = parsed.path
    if _has_path_traversal(path):
        return False, "Path traversal detected"
    if _is_internationalized_domain(hostname):
        return False, "Internationalized domain names not allowed"
    return True, ""


def extract_url_parts(url: str) -> dict[str, str | None]:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": str(parsed.port) if parsed.port else None,
        "path": parsed.path,
        "query": parsed.query,
        "fragment": parsed.fragment,
    }


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme
    host = parsed.hostname or ""
    port = parsed.port
    path = parsed.path or "/"
    while path.endswith("/") and len(path) > 1:
        path = path[:-1]
    netloc = host
    if port:
        netloc = f"{host}:{port}"
    query = parsed.query
    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized = f"{normalized}?{query}"
    return normalized


def validate_url(url: str) -> str:
    valid, reason = _validate_url_syntax(url)
    if not valid:
        return json_response(False, reason, code="validation_failed", details={"url": url})
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname and _is_private_host(hostname):
        return json_response(
            False,
            f"Blocked: internal/private host: {hostname}",
            code="ssrf_blocked",
            details={"url_hash": _url_hash(url), "host": hostname},
        )
    return json_response(True, "URL is valid", details={"url": url})


def _resolve_and_check_host(hostname: str) -> str | None:
    """Resolve hostname and check all IPs against private ranges.

    Uses a dedicated socket with a timeout instead of the global
    ``socket.setdefaulttimeout`` to avoid thread-safety side effects.

    Returns None if all resolved IPs are safe, or a string describing
    the first private IP found (for error messages).
    """
    try:
        for info in socket.getaddrinfo(hostname, None):
            resolved_ip = info[4][0]
            if isinstance(resolved_ip, str) and _is_private_host(resolved_ip):
                return resolved_ip
    except socket.gaierror:
        pass
    return None


class _DNSCheckingHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that verifies the resolved IP is not private."""

    def connect(self) -> None:
        private_ip = _resolve_and_check_host(self.host)
        if private_ip is not None:
            raise OSError(f"Blocked: host resolves to internal IP: {private_ip}")
        super().connect()


class _DNSCheckingHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that verifies the resolved IP is not private."""

    def connect(self) -> None:
        private_ip = _resolve_and_check_host(self.host)
        if private_ip is not None:
            raise OSError(f"Blocked: host resolves to internal IP: {private_ip}")
        super().connect()


class _LimitedRedirectHandler(HTTPRedirectHandler):
    """Custom redirect handler that limits redirects and blocks internal hosts."""

    def __init__(self, max_redirects: int = _MAX_REDIRECTS) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self._blocked_host: str | None = None

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        count = getattr(req, "_redirect_count", 0) + 1
        if count >= self.max_redirects:
            return None

        parsed_new = urlparse(newurl)
        hostname = parsed_new.hostname
        if hostname and _is_private_host(hostname):
            self._blocked_host = hostname
            return None

        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None:
            result._redirect_count = count  # type: ignore[attr-defined]
        return result


class _SafeHTTPHandler:
    """URL handler that uses DNS-checking connections for HTTP."""

    def http_open(self, req: Request) -> Any | None:
        return self._open(req, _DNSCheckingHTTPConnection)

    @staticmethod
    def _open(req: Request, connection_class: Any) -> Any | None:
        import urllib.request

        handler = urllib.request.AbstractHTTPHandler()
        return handler.do_open(connection_class, req)  # type: ignore[arg-type]


class _SafeHTTPSHandler:
    """URL handler that uses DNS-checking connections for HTTPS."""

    def https_open(self, req: Request) -> Any | None:
        return self._open(req, _DNSCheckingHTTPSConnection)

    @staticmethod
    def _open(req: Request, connection_class: Any) -> Any | None:
        import urllib.request

        handler = urllib.request.AbstractHTTPHandler()
        return handler.do_open(connection_class, req)  # type: ignore[arg-type]


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


async def read_url(url: str) -> str:
    """Read content from an http/https URL with strict security constraints."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return json_response(
            False,
            f"Unsupported URL scheme: {parsed.scheme or '(none)'}",
            code="blocked_scheme",
            details={"url_hash": _url_hash(url), "scheme": parsed.scheme},
        )

    hostname = parsed.hostname
    if hostname and _is_private_host(hostname):
        return json_response(
            False,
            f"Blocked: internal/private host: {hostname}",
            code="ssrf_blocked",
            details={"url_hash": _url_hash(url), "host": hostname},
        )

    redirect_handler = _LimitedRedirectHandler(max_redirects=_MAX_REDIRECTS)
    opener = build_opener(_SafeHTTPHandler, _SafeHTTPSHandler, redirect_handler)  # type: ignore[arg-type]

    try:
        req = Request(url, method="GET")
        resp = opener.open(req, timeout=_TIMEOUT_SECONDS)
    except HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308) and redirect_handler._blocked_host:
            redirect_handler._blocked_host = None
            return json_response(
                False,
                "Blocked: redirect to internal address",
                code="ssrf_blocked_redirect",
                details={"url_hash": _url_hash(url)},
            )
        return json_response(
            False,
            f"HTTP error: {exc.code} {exc.reason}",
            code="http_error",
            details={"url_hash": _url_hash(url), "http_code": exc.code},
        )
    except URLError as exc:
        reason = str(exc.reason) if exc.reason else "unknown"
        return json_response(
            False,
            f"Connection failed: {reason}",
            code="connection_error",
            details={"url_hash": _url_hash(url), "reason": reason},
        )
    except TimeoutError:
        return json_response(
            False,
            "Request timed out",
            code="timeout",
            details={"url_hash": _url_hash(url), "timeout_s": _TIMEOUT_SECONDS},
        )
    except OSError as exc:
        err_str = str(exc)
        if "internal IP" in err_str or "private IP" in err_str:
            return json_response(
                False,
                err_str,
                code="ssrf_blocked",
                details={"url_hash": _url_hash(url)},
            )
        if "too many redirects" in err_str.lower() or "redirect" in err_str.lower():
            return json_response(
                False,
                "Too many redirects",
                code="redirect_limit",
                details={
                    "url_hash": _url_hash(url),
                    "max_redirects": _MAX_REDIRECTS,
                },
            )
        return json_response(
            False,
            f"Request error: {exc}",
            code="request_error",
            details={"url_hash": _url_hash(url), "error": str(exc)},
        )

    content_type = resp.headers.get_content_type()
    allowed = {"text/plain", "text/css", "text/csv"}
    ct_lower = content_type.lower() if content_type else ""
    if ct_lower not in allowed:
        return json_response(
            False,
            "Blocked: non-text content type",
            code="content_type_blocked",
            details={
                "url_hash": _url_hash(url),
                "content_type": content_type or "(unknown)",
            },
        )

    content_length_raw = resp.headers.get("content-length")
    content_length: int | None = None
    if content_length_raw is not None:
        try:
            content_length = int(content_length_raw)
        except (ValueError, TypeError):
            pass

    try:
        body = resp.read(_MAX_SIZE + 1)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to read response body: {exc}",
            code="read_error",
            details={"url_hash": _url_hash(url), "error": str(exc)},
        )

    if len(body) > _MAX_SIZE:
        return json_response(
            False,
            "Response exceeded maximum allowed size",
            code="too_large",
            details={
                "url_hash": _url_hash(url),
                "max_size_bytes": _MAX_SIZE,
                "received_bytes": len(body),
            },
        )

    text = body.decode("utf-8", errors="replace")
    truncated = len(text) > _RESPONSE_TRUNCATION
    response_text = text[:_RESPONSE_TRUNCATION] if truncated else text

    return json_response(
        True,
        "Read URL successfully",
        details={
            "url_hash": _url_hash(url),
            "content_type": content_type,
            "content_length": content_length,
            "content": response_text,
            "truncated": truncated,
        },
    )
