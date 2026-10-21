"""Read-only status endpoint must not expose keys or require a model call."""
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StatusTest(unittest.TestCase):
    def test_safe_status_reads_bundled_manifest_and_runtime_environment(self):
        spec = importlib.util.spec_from_file_location("guide_status", ROOT / "cloud-functions" / "guide-status" / "index.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.handler.context = SimpleNamespace(env={"AI_GATEWAY_API_KEY": "private-test-value", "AI_GATEWAY_BASE_URL": "https://gateway.example.invalid/v1", "AI_GATEWAY_MODEL": "@makers/deepseek-v4-flash"})
        module.handler.log_message = lambda *args: None
        server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            conn.request("GET", "/guide-status")
            response = conn.getresponse()
            raw = response.read().decode()
            value = json.loads(raw)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            corpus_bytes = (ROOT / "agents" / "_knowledge" / "corpus.json").read_bytes()
            self.assertEqual(value["source_count"], len(json.loads(corpus_bytes)["sources"]))
            manifest = json.loads((ROOT / "cloud-functions" / "guide-status" / "knowledge-status.json").read_text())
            self.assertEqual(value["corpus_version"], manifest["corpus_version"])
            self.assertEqual(value["model"], "@makers/deepseek-v4-flash")
            self.assertEqual(value["gateway_hostname"], "gateway.example.invalid")
            self.assertTrue(value["llm_configured"])
            self.assertNotIn("private-test-value", raw)
            self.assertNotIn("/v1", raw)
            self.assertEqual(value["corpus_sha256"], hashlib.sha256(corpus_bytes).hexdigest())
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(1)


if __name__ == "__main__": unittest.main()
