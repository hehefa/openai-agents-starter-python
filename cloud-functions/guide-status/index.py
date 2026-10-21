"""GET /guide-status: read-only deployment check; makes no model request."""
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        context = getattr(self, "context", None)
        runtime_env = getattr(context, "env", None)
        if runtime_env is None:
            runtime_env = getattr(getattr(context, "agent", None), "env", None)

        def env(name, default=None):
            if runtime_env is not None:
                value = runtime_env.get(name) if hasattr(runtime_env, "get") else getattr(runtime_env, name, None)
                if value:
                    return str(value)
            return os.getenv(name, default)

        try:
            path = Path(__file__).with_name("knowledge-status.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            base_url = env("AI_GATEWAY_BASE_URL") or ""
            result = {
                "corpus_version": payload.get("corpus_version"),
                "source_count": payload.get("source_count"),
                "corpus_sha256": payload.get("corpus_sha256"),
                "llm_configured": bool(env("AI_GATEWAY_API_KEY") and base_url),
                "model": env("AI_GATEWAY_MODEL", "@makers/deepseek-v4-flash"),
                "gateway_hostname": urlsplit(base_url).hostname,
            }
            status = 200
        except Exception:
            # A failed knowledge check must not disclose paths or environment.
            result, status = {"ready": False}, 503
        raw = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
