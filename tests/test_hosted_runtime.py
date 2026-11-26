import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agentops.contracts import LabError
from agentops.delivery_azure import project_shape
from agentops.hosted_runtime import events, respond


class HostedAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_events_preserve_mcp_calls_and_usage(self):
        response = {
            "status": "completed", "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            "output": [
                {"id": "mcp_" + "a" * 50, "type": "mcp_call", "name": "knowledge_base_retrieve",
                 "server_label": "knowledge-base", "arguments": "{}", "output": "{}",
                 "status": "completed"},
                {"id": "msg_" + "b" * 50, "type": "message", "role": "assistant",
                 "status": "completed", "content": [{"type": "output_text", "text": "Synthetic reply",
                                                    "annotations": []}]},
            ],
        }
        actual = [item async for item in events({"input": "test"}, "resp_123456789", response)]
        self.assertEqual(actual[0]["type"], "response.created")
        self.assertEqual(actual[-1]["type"], "response.completed")
        self.assertEqual(project_shape(actual[-1]["response"]["output"], response["output"]), response["output"])
        self.assertEqual(actual[-1]["response"]["usage"], response["usage"])
        response["status"] = "failed"
        with self.assertRaisesRegex(LabError, "did not complete"):
            _ = [item async for item in events({"input": "test"}, "resp_123456789", response)]

    async def test_calls_both_configured_transports_not_an_echo(self):
        project, client, result = Mock(), AsyncMock(), Mock()
        project.get_openai_client.return_value.__aenter__ = AsyncMock(return_value=client)
        project.get_openai_client.return_value.__aexit__ = AsyncMock(return_value=False)
        client.responses.create.return_value = result
        result.model_dump.return_value = {"status": "completed", "output": ["upstream"]}
        tools = [{"server_label": "knowledge-base", "type": "mcp"},
                 {"server_label": "lab-tools", "type": "mcp"}]
        env = {"DELIVERY_TOOLS_JSON": json.dumps(tools), "DELIVERY_NEGATIVE_CONTROL": "false",
               "FOUNDRY_MODEL_NAME": "gpt-5-mini", "DELIVERY_INSTRUCTIONS": "Use both tools"}
        with patch.dict("os.environ", env):
            response = await respond("Not an echo", project, {"release_digest": "a" * 64})
        self.assertEqual(response["output"], ["upstream"])
        call = client.responses.create.call_args.kwargs
        self.assertEqual(call["tools"], tools)
        self.assertEqual(call["metadata"], {"release_digest": "a" * 64})
        self.assertFalse(call["store"])
