# tests/test_http_transport.py
"""Smoke tests for the streamable-http transport.

Focus on the two things that the stdio tests can't cover:
    * the Bearer-token middleware returns 401 for unauthenticated requests,
    * the server refuses to bind to a non-loopback interface without a token.

The MCP protocol layer itself is exercised by the stdio tests and by the mcp
package's own test suite, so we don't re-run a full handshake here.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"port {port} never opened")


def _post(url: str, headers: dict | None = None) -> int:
    req = urllib.request.Request(url, data=b"{}", headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _fetch(url: str, method: str = "GET", headers: dict | None = None) -> tuple[int, str, dict]:
    req = urllib.request.Request(
        url, data=b"{}" if method == "POST" else None, headers=headers or {}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), dict(e.headers)


def test_http_rejects_without_token(tmp_vault):
    from second_brain_mcp import indexer

    indexer.rebuild()

    port = _free_port()
    env = os.environ.copy()
    env["OBSIDIAN_HTTP_TOKEN"] = "s3cret"
    env["OBSIDIAN_MCP_HOST"] = "127.0.0.1"
    env["OBSIDIAN_MCP_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "second_brain_mcp.cli", "serve", "--transport", "http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        url = f"http://127.0.0.1:{port}/mcp"
        assert _post(url) == 401
        assert _post(url, {"authorization": "Bearer wrong"}) == 401
        # A correct Bearer token gets past the middleware — the MCP layer may
        # answer anything >= 200; we only care that auth passes (not 401).
        assert _post(url, {"authorization": "Bearer s3cret"}) != 401
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_401_carries_www_authenticate_bearer_header(tmp_vault):
    """Without WWW-Authenticate, MCP SDKs assume OAuth and crash on discovery."""
    from second_brain_mcp import indexer

    indexer.rebuild()

    port = _free_port()
    env = os.environ.copy()
    env["OBSIDIAN_HTTP_TOKEN"] = "s3cret"
    env["OBSIDIAN_MCP_HOST"] = "127.0.0.1"
    env["OBSIDIAN_MCP_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "second_brain_mcp.cli", "serve", "--transport", "http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        status, _body, headers = _fetch(f"http://127.0.0.1:{port}/mcp", method="POST")
        assert status == 401
        www_auth = headers.get("www-authenticate") or headers.get("WWW-Authenticate")
        assert www_auth is not None, "401 must carry WWW-Authenticate so SDKs skip OAuth"
        assert www_auth.lower().startswith("bearer")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_oauth_discovery_no_oauth_endpoints_json_404(tmp_vault):
    """Endpoints the server does NOT implement must 404 in JSON, not plain text.
    Claude Code's MCP SDK JSON-parses these responses; plain 'Not Found' crashes
    the parser and blocks the Bearer-from-config fallback."""
    from second_brain_mcp import indexer

    indexer.rebuild()

    port = _free_port()
    env = os.environ.copy()
    env["OBSIDIAN_HTTP_TOKEN"] = "s3cret"
    env["OBSIDIAN_MCP_HOST"] = "127.0.0.1"
    env["OBSIDIAN_MCP_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "second_brain_mcp.cli", "serve", "--transport", "http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)

        for probe_path, method in [
            ("/.well-known/oauth-authorization-server", "GET"),
            ("/register", "POST"),
        ]:
            status, body, headers = _fetch(
                f"http://127.0.0.1:{port}{probe_path}", method=method
            )
            assert status == 404, f"{probe_path} should 404"
            content_type = headers.get("content-type") or headers.get("Content-Type") or ""
            assert "application/json" in content_type, (
                f"{probe_path} returned {content_type!r}, SDK will choke on non-JSON"
            )
            parsed = json.loads(body)  # must not raise
            assert parsed.get("error") == "not_supported"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_protected_resource_metadata_advertises_bearer(tmp_vault):
    """RFC 9728: /.well-known/oauth-protected-resource returns 200 JSON metadata
    telling MCP clients we accept Bearer in the Authorization header — no OAuth
    flow needed. Without this a compliant SDK won't know how to authenticate
    even though the static Bearer in its config would work."""
    from second_brain_mcp import indexer

    indexer.rebuild()

    port = _free_port()
    env = os.environ.copy()
    env["OBSIDIAN_HTTP_TOKEN"] = "s3cret"
    env["OBSIDIAN_MCP_HOST"] = "127.0.0.1"
    env["OBSIDIAN_MCP_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "second_brain_mcp.cli", "serve", "--transport", "http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)

        status, body, headers = _fetch(
            f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource",
            method="GET",
        )
        assert status == 200
        content_type = headers.get("content-type") or headers.get("Content-Type") or ""
        assert "application/json" in content_type
        parsed = json.loads(body)
        assert parsed.get("resource", "").endswith("/mcp")
        assert "header" in parsed.get("bearer_methods_supported", [])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_refuses_nonloopback_without_token(tmp_vault):
    """Safety rail: don't open the MCP to the network without auth."""
    from second_brain_mcp import indexer

    indexer.rebuild()

    env = os.environ.copy()
    env.pop("OBSIDIAN_HTTP_TOKEN", None)
    env["OBSIDIAN_MCP_HOST"] = "0.0.0.0"
    env["OBSIDIAN_MCP_PORT"] = str(_free_port())

    proc = subprocess.run(
        [sys.executable, "-m", "second_brain_mcp.cli", "serve", "--transport", "http"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode != 0
    assert "non-loopback" in proc.stderr or "non-loopback" in proc.stdout
