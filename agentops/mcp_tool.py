"""A read-only MCP transport with a deterministic backend and Entra caller checks."""

from __future__ import annotations

import argparse
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from uuid import uuid4

from .contracts import ENVIRONMENTS, LabError, canonical, digest_value, fields, fingerprint, parse_json, require
from .delivery_contracts import FEATURE, TOOL_NAME, TOOL_SCHEMA

FIXTURES = {
    "dev": {"enabled": True, "fixture_revision": "dev-1"},
    "test": {"enabled": False, "fixture_revision": "test-2"},
    "labprod": {"enabled": False, "fixture_revision": "labprod-1"},
}
PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")


def dispatch(request: dict, environment: str, caller: str | None = None,
             release_digest: str | None = None) -> dict | None:
    fields(request, {"jsonrpc", "method"}, {"id", "params"})
    require(request["jsonrpc"] == "2.0", "Unsupported JSON-RPC")
    method = request["method"]
    if method == "notifications/initialized" and "id" not in request:
        return None
    require("id" in request, "Request ID required")
    if method == "initialize":
        params = request.get("params", {})
        fields(params, {"protocolVersion"}, {"capabilities", "clientInfo", "_meta"})
        requested = params["protocolVersion"]
        require(isinstance(requested, str) and bool(requested), "MCP protocol version required")
        # MCP negotiation: an unsupported request gets the latest supported version, and the
        # client decides whether to continue.
        result = {"protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[-1],
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
        fields(params, {"name", "arguments"}, {"_meta"})
        require(params["name"] == TOOL_NAME, "Tool is not allowlisted")
        fields(params["arguments"], {"feature_id"})
        require(params["arguments"]["feature_id"] == FEATURE, "Unknown feature")
        payload = {"feature_id": FEATURE, "environment": environment,
                   "backend": "deterministic-lab-fixture", **FIXTURES[environment]}
        if caller is not None:
            payload["_auth"] = {"principal_digest": fingerprint({"principal_id": caller}),
                                "trace_id": str(uuid4())}
            if release_digest is not None:
                digest_value(release_digest, "MCP release binding")
                payload["_auth"]["release_digest"] = release_digest
            logging.getLogger("agentops.mcp").info(canonical({
                "event": "mcp.tool.completed", "environment": environment, "tool_name": TOOL_NAME,
                **payload["_auth"],
            }).decode().strip())
        result = {"structuredContent": payload,
                  "content": [{"type": "text", "text": canonical(payload).decode().strip()}],
                  "isError": False}
    else:
        raise LabError("Method is not supported")
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def entra_verifier(tenant: str, audience: str, allowed_callers: set[str]) -> Callable[[str], str]:
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
            raise LabError("Invalid access token: " + type(exc).__name__) from exc
        require(claims["tid"] == tenant and claims["oid"] in allowed_callers,
                "Caller is not authorized in this environment: principal_digest="
                + fingerprint({"principal_id": str(claims["oid"])})[:16])
        return claims["oid"]
    return verify


MAX_BODY = 16384


def read_body(rfile, headers) -> bytes:
    """Read one bounded request body framed by Content-Length or chunked transfer coding."""
    encoding = headers.get("Transfer-Encoding")
    if encoding is None:
        size = int(headers.get("Content-Length", "0"))
        require(0 < size <= MAX_BODY, "Request is missing or too large")
        body = rfile.read(size)
        require(len(body) == size, "Incomplete request")
        return body
    # The Foundry MCP client streams requests with chunked coding and no Content-Length.
    require(encoding.strip().lower() == "chunked" and headers.get("Content-Length") is None,
            "Unsupported transfer encoding")
    body = bytearray()
    while True:
        line = rfile.readline(80)
        match = re.fullmatch(rb"([0-9A-Fa-f]{1,8})(?:;[^\r\n]*)?\r\n", line)
        require(match is not None, "Invalid chunk size")
        size = int(match.group(1), 16)
        require(len(body) + size <= MAX_BODY, "Request is missing or too large")
        if size == 0:
            break
        chunk = rfile.read(size)
        require(len(chunk) == size and rfile.read(2) == b"\r\n", "Incomplete request")
        body += chunk
    for _ in range(9):
        trailer = rfile.readline(1024)
        require(trailer.endswith(b"\r\n"), "Incomplete request")
        if trailer == b"\r\n":
            require(bool(body), "Request is missing or too large")
            return bytes(body)
    raise LabError("Too many trailers")


def outcome(status: int, reason: str, request: object = None, framing: str | None = None) -> str:
    """One request outcome without headers, tokens, bodies or argument values."""
    record = {"event": "mcp.request", "status": status, "reason": reason[:160]}
    if framing is not None:
        record["framing"] = framing
    if isinstance(request, dict):
        method = request.get("method")
        if isinstance(method, str) and re.fullmatch(r"[a-z/_]{1,64}", method):
            record["method"] = method
        params = request.get("params")
        if isinstance(params, dict):
            record["param_keys"] = sorted(key for key in params if re.fullmatch(r"[A-Za-z_]{1,40}", key))[:10]
            version = params.get("protocolVersion")
            if isinstance(version, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
                record["protocol_version"] = version
    return canonical(record).decode().strip()


def handler(environment: str, verify: Callable[[str], str]):
    require(environment in ENVIRONMENTS, "Unknown environment")

    log = logging.getLogger("agentops.mcp")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # HTTP access logs must never include request headers, tokens or bodies.
            return

        def do_GET(self):
            self.send_response(405 if re.fullmatch(r"/mcp(?:/releases/[0-9a-f]{64})?", self.path) else 404)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            route = re.fullmatch(r"/mcp(?:/releases/([0-9a-f]{64}))?", self.path)
            if route is None:
                self.send_error(404)
                return
            framing = "chunked" if self.headers.get("Transfer-Encoding") is not None else "length"
            try:
                self.connection.settimeout(10)
                body = read_body(self.rfile, self.headers)
            except (LabError, ValueError, OSError) as exc:
                log.info(outcome(400, "body: " + (str(exc) if isinstance(exc, LabError) else type(exc).__name__),
                                 framing=framing))
                # The body may be partly unread, so the connection cannot be reused.
                self.close_connection = True
                self.send_error(400, "Invalid request body")
                return
            try:
                caller = verify(self.headers.get("Authorization", ""))
                require(isinstance(caller, str) and bool(caller), "Authenticated principal missing")
            except LabError as exc:
                log.info(outcome(401, "auth: " + str(exc), framing=framing))
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            request = {}
            try:
                require(self.headers.get_content_type() == "application/json", "JSON required")
                request = parse_json(body)
                result = dispatch(request, environment, caller, route.group(1))
                status = 202 if result is None else 200
                reason = "ok"
            except (LabError, ValueError, UnicodeError) as exc:
                result = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                          "error": {"code": -32602, "message": "Invalid or unsupported request"}}
                status = 400
                reason = "request: " + (str(exc) if isinstance(exc, LabError) else type(exc).__name__)
            log.info(outcome(status, reason, request, framing))
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
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    verify = entra_verifier(os.environ["AZURE_TENANT_ID"], os.environ["MCP_AUDIENCE"],
                            set(os.environ["MCP_ALLOWED_CALLER_IDS"].split(",")))
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler(args.environment, verify)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
