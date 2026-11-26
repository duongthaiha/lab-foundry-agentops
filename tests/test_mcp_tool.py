import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from agentops.contracts import LabError, canonical, fingerprint
from agentops.delivery_contracts import FEATURE, TOOL_NAME
from agentops.mcp_tool import dispatch, entra_verifier, handler


class McpTransportTests(unittest.TestCase):
    def test_real_signature_tenant_audience_expiry_and_caller_checks(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tenant, audience, caller = ("a" * 8 + "-0000-0000-0000-" + "a" * 12,
                                     "b" * 8 + "-0000-0000-0000-" + "b" * 12,
                                     "c" * 8 + "-0000-0000-0000-" + "c" * 12)
        now = int(time.time())
        claims = {"iss": f"https://login.microsoftonline.com/{tenant}/v2.0", "tid": tenant,
                  "aud": audience, "oid": caller, "iat": now, "nbf": now, "exp": now + 60}
        with patch("jwt.PyJWKClient") as jwks:
            jwks.return_value.get_signing_key_from_jwt.return_value = Mock(key=key.public_key())
            verify = entra_verifier(tenant, "api://" + audience, {caller})
            self.assertEqual(verify("Bearer " + jwt.encode(claims, key, algorithm="RS256")), caller)
            for changed in ({"aud": "foreign"}, {"tid": "foreign"}, {"oid": "foreign"},
                            {"exp": now - 1}, {"iss": "https://sts.windows.net/" + tenant + "/"}):
                token = jwt.encode({**claims, **changed}, key, algorithm="RS256")
                with self.subTest(changed=changed), self.assertRaises(LabError):
                    verify("Bearer " + token)

    def test_real_http_transport_is_authenticated_and_environment_specific(self):
        for environment, enabled in (("dev", True), ("test", False), ("labprod", False)):
            def verify(header):
                if header != "Bearer unit-test-only":
                    raise LabError("Unauthorized")
                return "synthetic-test-caller"
            with ThreadingHTTPServer(("127.0.0.1", 0), handler(environment, verify)) as server:
                worker = threading.Thread(target=server.serve_forever)
                worker.start()
                try:
                    url = f"http://127.0.0.1:{server.server_port}/mcp"
                    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": TOOL_NAME, "arguments": {"feature_id": FEATURE}}}
                    request = Request(url, data=canonical(body), headers={"Content-Type": "application/json"})
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(request, timeout=5)
                    self.assertEqual(denied.exception.code, 401)
                    denied.exception.close()
                    for method, params in (("initialize", {"protocolVersion": "2025-03-26"}),
                                           ("tools/list", {})):
                        handshake = Request(
                            url, data=canonical({"jsonrpc": "2.0", "id": 2, "method": method, "params": params}),
                            headers={"Content-Type": "application/json", "Authorization": "Bearer unit-test-only"})
                        with urlopen(handshake, timeout=5) as response:
                            self.assertIn("result", json.load(response))
                    request.add_header("Authorization", "Bearer unit-test-only")
                    with urlopen(request, timeout=5) as response:
                        payload = json.load(response)["result"]["structuredContent"]
                    self.assertIs(payload["enabled"], enabled)
                    self.assertEqual(payload["environment"], environment)
                    self.assertEqual(payload["backend"], "deterministic-lab-fixture")
                    self.assertEqual(payload["_auth"]["principal_digest"],
                                     fingerprint({"principal_id": "synthetic-test-caller"}))
                    self.assertNotIn("synthetic-test-caller", json.dumps(payload))
                    with urlopen(request, timeout=5) as response:
                        repeated = json.load(response)["result"]["structuredContent"]
                    self.assertNotEqual(payload["_auth"]["trace_id"], repeated["_auth"]["trace_id"])
                finally:
                    server.shutdown()
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())

    def test_initialization_and_tool_schema_exclude_writes(self):
        initialized = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-03-26"}}, "dev")
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-03-26")
        result = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "dev")
        self.assertEqual(len(result["result"]["tools"]), 1)
        self.assertTrue(result["result"]["tools"][0]["annotations"]["readOnlyHint"])
        for arguments in ({"feature_id": FEATURE, "environment": "test"}, {"feature_id": "unknown"}):
            with self.assertRaises(LabError):
                dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": TOOL_NAME, "arguments": arguments}}, "dev")
        with self.assertRaises(LabError):
            dispatch({"jsonrpc": "2.0", "id": 4, "method": "delete"}, "dev")
