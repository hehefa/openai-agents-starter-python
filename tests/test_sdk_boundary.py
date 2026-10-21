"""Exercise the real Agents SDK against a loopback fake gateway, never a provider."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import sys
import threading
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
pkg = ModuleType("works_runtime")
pkg.__path__ = [str(ROOT / "agents")]
sys.modules.setdefault("works_runtime", pkg)
chat = importlib.import_module("works_runtime.chat.index")


class SdkBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_only_length_finish_is_sdk_behavior_error(self):
        # This is an offline reproduction of one possible SDK failure path, not
        # proof of the cause of any particular production ModelBehaviorError.
        from agents.exceptions import ModelBehaviorError
        from agents.models.chatcmpl_stream_handler import ChatCmplStreamHandler
        from openai.types.chat import ChatCompletionChunk
        from openai.types.responses import Response

        async def chunks():
            yield ChatCompletionChunk(
                id="offline", created=0, model="@makers/deepseek-v4-flash",
                object="chat.completion.chunk",
                choices=[{"index": 0, "delta": {"reasoning_content": "offline reasoning only"}, "finish_reason": None}],
            )
            yield ChatCompletionChunk(
                id="offline", created=0, model="@makers/deepseek-v4-flash",
                object="chat.completion.chunk",
                choices=[{"index": 0, "delta": {}, "finish_reason": "length"}],
                usage={"prompt_tokens": 100, "completion_tokens": 1200, "total_tokens": 1300},
            )
        response = Response.model_construct(
            id="offline", created_at=0, model="@makers/deepseek-v4-flash", object="response",
            output=[], parallel_tool_calls=False, tool_choice="auto", tools=[], usage=None,
        )
        with self.assertRaisesRegex(ModelBehaviorError, "finish_reason='length'.*no assistant text"):
            async for _ in ChatCmplStreamHandler.handle_stream(
                response, chunks(), model="@makers/deepseek-v4-flash",
                raise_on_length_truncation=True, require_finish_reason=False,
            ):
                pass

    async def test_real_sdk_stream_and_explicit_runtime_config(self):
        requests = []
        answer = json.dumps({"blocks": [{"text": "YourTube is a 2018 installation.", "evidence_ids": ["E1"]}], "uncertain": False})
        class Gateway(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for part in [answer[:30], answer[30:]]:
                    payload = {"id": "local-test", "object": "chat.completion.chunk", "created": 1,
                               "model": "@makers/deepseek-v4-flash", "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]}
                    self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                payload = {"id": "local-test", "object": "chat.completion.chunk", "created": 1,
                           "model": "@makers/deepseek-v4-flash", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime_env = {"AI_GATEWAY_API_KEY": "local-placeholder", "AI_GATEWAY_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}
            # This failing OS-level URL establishes that runtime context takes
            # precedence. No remote URL is used by the actual request.
            with patch.dict(os.environ, {"AI_GATEWAY_BASE_URL": "http://127.0.0.1:1/v1", "AI_GATEWAY_MODEL": "@makers/deepseek-v4-flash"}):
                result = await asyncio.wait_for(chat._run_model("Use the given evidence.", asyncio.Event(), runtime_env), 5)
            self.assertEqual(json.loads(result), json.loads(answer))
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["model"], "@makers/deepseek-v4-flash")
            self.assertTrue(requests[0]["stream"])
            self.assertEqual(requests[0].get("max_tokens") or requests[0].get("max_completion_tokens"), 2400)
            self.assertEqual(requests[0]["thinking"], {"type": "disabled"})
            self.assertFalse(requests[0].get("tools"))
            # The actual SDK request must retain both positive authorship facts
            # and the formal English-edition boundary supplied to the agent.
            instructions = " ".join(str(message.get("content", "")) for message in requests[0]["messages"] if message["role"] in ("system", "developer"))
            for contract in ("both facts coexist", "an attitude He Fa insists on", "do not downgrade his director identity", "Do not volunteer end-credit audits", "formal complete English edition", "not an independent English monograph"):
                self.assertIn(contract, instructions)
            self.assertNotIn("verbatim transcription", instructions)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)


if __name__ == "__main__": unittest.main()
