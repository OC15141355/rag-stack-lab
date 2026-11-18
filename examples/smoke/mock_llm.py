"""Tiny fake OpenAI-compatible server for testing smoke.py. Modes via env MOCK_MODE: good | buffered | notools."""
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = os.environ.get("MOCK_MODE", "good")
KEY = "test-key"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _authed(self):
        return self.headers.get("Authorization") == f"Bearer {KEY}"

    def do_GET(self):
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        self._json(200, {"data": [{"id": "test-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': str(i) + ','}}]})}\n\n" for i in range(1, 31)]
            if MODE == "buffered":
                time.sleep(1.5); self.wfile.write("".join(chunks).encode())
            else:
                for ch in chunks:
                    self.wfile.write(ch.encode()); self.wfile.flush(); time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n"); return
        if body.get("tools"):
            if MODE == "notools":
                msg = {"role": "assistant", "content": '<tool_call>{"name":"get_weather"}</tool_call>'}
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
                       "function": {"name": "get_weather", "arguments": json.dumps({"city": "Sydney"})}}]}
            return self._json(200, {"choices": [{"message": msg, "finish_reason": "tool_calls"}]})
        n = len(body["messages"][0]["content"].split())
        if n > 50000:
            return self._json(400, {"error": f"context length {n} exceeds 50000"})
        self._json(200, {"choices": [{"message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": n, "completion_tokens": 1}})


ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "18080"))), H).serve_forever()
