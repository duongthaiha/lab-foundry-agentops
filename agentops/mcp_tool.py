"""A read-only MCP transport with a deterministic backend and Entra caller checks."""

from __future__ import annotations

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .contracts import ENVIRONMENTS, LabError, canonical, fields, parse_json, require
from .delivery_contracts import FEATURE, TOOL_NAME, TOOL_SCHEMA

FIXTURES = {
    "dev": {"enabled": True, "fixture_revision": "dev-1"},
    "test": {"enabled": False, "fixture_revision": "test-2"},
    "labprod": {"enabled": False, "fixture_revision": "labprod-1"},
}


def dispatch(request: dict, environment: str) -> dict | None:
    fields(request, {"jsonrpc", "method"}, {"id", "params"})
    require(request["jsonrpc"] == "2.0", "Unsupported JSON-RPC")
    method = request["method"]
    if method == "notifications/initialized" and "id" not in request:
        return None
    require("id" in request, "Request ID required")
    if method == "initialize":
        params = request.get("params", {})
        fields(params, {"protocolVersion"}, {"capabilities", "clientInfo"})
        require(params.get("protocolVersion") in ("2024-11-05", "2025-03-26", "2025-06-18"),
                "Unsupported MCP protocol")
        result = {"protocolVersion": params["protocolVersion"],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "contoso-lab-status", "version": "1.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{
            "name": TOOL_NAME, "description": "Read the fictional feature flag for this lab environment.",
            "inputSchema": TOOL_SCHEMA,
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
        }]}
    elif method == "tools/call":
        params = request.get("params")
        fields(params, {"name", "arguments"})
        require(params["name"] == TOOL_NAME, "Tool is not allowlisted")
        fields(params["arguments"], {"feature_id"})
        require(params["arguments"]["feature_id"] == FEATURE, "Unknown feature")
        payload = {"feature_id": FEATURE, "environment": environment,
                   "backend": "deterministic-lab-fixture", **FIXTURES[environment]}
        result = {"structuredContent": payload,
                  "content": [{"type": "text", "text": canonical(payload).decode().strip()}],
                  "isError": False}
    else:
        raise LabError("Method is not supported")
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def entra_verifier(tenant: str, audience: str, allowed_callers: set[str]) -> Callable[[str], str]:
    import re
    import jwt

    require(re.fullmatch(r"[0-9a-f-]{36}", tenant) is not None, "Tenant GUID required")
    require(re.fullmatch(r"api://[0-9a-f-]{36}", audience) is not None,
            "Reviewed api://application-id audience required")
    require(bool(allowed_callers) and all(re.fullmatch(r"[0-9a-f-]{36}", oid) for oid in allowed_callers),
            "Caller object-ID allowlist required")
    issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
    keys = jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
                         timeout=10)

    def verify(header: str) -> str:
        require(header.startswith("Bearer "), "Bearer authentication required")
        token = header[7:]
        try:
            key = keys.get_signing_key_from_jwt(token)
            # Entra v2 tokens carry the resource's application ID, not its api:// URI.
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=audience[6:],
                                issuer=issuer, options={"require": ["exp", "iat", "nbf", "oid", "tid"]})
        except jwt.PyJWTError as exc:
            raise LabError("Invalid access token") from exc
        require(claims["tid"] == tenant and claims["oid"] in allowed_callers,
                "Caller is not authorized in this environment")
        return claims["oid"]
    return verify


def handler(environment: str, verify: Callable[[str], str]):
    require(environment in ENVIRONMENTS, "Unknown environment")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # HTTP access logs must never include request headers, tokens or bodies.
            return

        def do_GET(self):
            self.send_response(405 if self.path == "/mcp" else 404)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if self.path != "/mcp":
                self.send_error(404)
                return
            try:
                self.connection.settimeout(10)
                size = int(self.headers.get("Content-Length", "0"))
                require(0 < size <= 16384, "Request is missing or too large")
                body = self.rfile.read(size)
                require(len(body) == size, "Incomplete request")
            except (LabError, ValueError, OSError):
                self.send_error(400, "Invalid request body")
                return
            try:
                verify(self.headers.get("Authorization", ""))
            except LabError:
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            request = {}
            try:
                require(self.headers.get_content_type() == "application/json", "JSON required")
                request = parse_json(body)
                result = dispatch(request, environment)
                status = 202 if result is None else 200
            except (LabError, ValueError, UnicodeError):
                result = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                          "error": {"code": -32602, "message": "Invalid or unsupported request"}}
                status = 400
            data = b"" if result is None else canonical(result)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    verify = entra_verifier(os.environ["AZURE_TENANT_ID"], os.environ["MCP_AUDIENCE"],
                            set(os.environ["MCP_ALLOWED_CALLER_IDS"].split(",")))
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler(args.environment, verify)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
