"""Fake Bifrost/OpenAI endpoint for smoke tests.
MOCK_MODE: good | buffered | notools | generic401 | flaky429 ; MOCK_RPM: main-key requests/min before 429 ;
MOCK_VK: main key ; MOCK_VK_PROBE: probe key limited to MOCK_PROBE_RPM (default 2)."""
import json, os, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = os.environ.get("MOCK_MODE", "good")
VK = os.environ.get("MOCK_VK", "sk-bf-test")
RPM = int(os.environ.get("MOCK_RPM", "1000"))
VK_PROBE = os.environ.get("MOCK_VK_PROBE", "sk-bf-probe")
PROBE_RPM = int(os.environ.get("MOCK_PROBE_RPM", "2"))
_lock, _hits, _probe_hits, _flaky = threading.Lock(), [], [], {"n": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _gate(self):
        if self.headers.get("x-bf-vk") == VK_PROBE:
            with _lock:
                now = time.time(); _probe_hits[:] = [t for t in _probe_hits if now - t < 60]; _probe_hits.append(now)
                if len(_probe_hits) > PROBE_RPM:
                    self._json(429, {"error": {"message": "rate limit exceeded", "type": "rate_limited"}}); return False
            return True
        if self.headers.get("x-bf-vk") != VK:
            if MODE == "generic401": self._json(401, {"error": "unauthorized"})
            else: self._json(401, {"error": {"message": "virtual key is required", "type": "virtual_key_required"}})
            return False
        with _lock:
            now = time.time(); _hits[:] = [t for t in _hits if now - t < 60]; _hits.append(now)
            if len(_hits) > RPM:
                self._json(429, {"error": {"message": "rate limit exceeded", "type": "rate_limited"}}); return False
        if MODE == "flaky429":
            with _lock:
                _flaky["n"] += 1
                if _flaky["n"] % 3 == 1:
                    self.send_response(429); self.send_header("Retry-After", "1"); self.send_header("Content-Length", "0")
                    self.end_headers(); return False
        return True
    def do_GET(self):
        if not self._gate(): return
        self._json(200, {"data": [{"id": "test-model"}]})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self._gate(): return
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': str(i) + ','}}]})}\n\n" for i in range(1, 31)]
            if MODE == "buffered":
                time.sleep(1.5); self.wfile.write("".join(chunks).encode())
            else:
                for ch in chunks: self.wfile.write(ch.encode()); self.wfile.flush(); time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n"); return
        if body.get("tools"):
            msg = ({"role": "assistant", "content": '<tool_call>{"name":"get_weather"}</tool_call>'} if MODE == "notools"
                   else {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
                         "function": {"name": "get_weather", "arguments": json.dumps({"city": "Sydney"})}}]})
            return self._json(200, {"choices": [{"message": msg, "finish_reason": "tool_calls"}]})
        n = len(body["messages"][0]["content"].split())
        self._json(200, {"choices": [{"message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": n, "completion_tokens": 1}})

ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "18080"))), H).serve_forever()
