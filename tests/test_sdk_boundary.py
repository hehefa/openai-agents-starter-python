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
            self.assertEqual(requests[0].get("max_tokens") or requests[0].get("max_completion_tokens"), 1200)
            self.assertFalse(requests[0].get("tools"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)


if __name__ == "__main__": unittest.main()
