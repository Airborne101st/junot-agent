"""Talk to Junot in your browser:  uv run python -m junot.web  ->  http://127.0.0.1:8765

The web gateway: one page, and one endpoint, POST /chat, that calls
Junot.respond(). Python's own http.server, no framework, no dependency.

It listens on 127.0.0.1 only. That address is reachable from this laptop and
nowhere else; 0.0.0.0 would let anyone on your Wi-Fi read your notes. There
is no login, so that one line is the whole security model.

HTTPServer handles one request at a time, which is also what Junot needs:
one agent, one turn at a time, on one SQLite connection.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from junot.app import Junot
from junot.config import load_settings

HOST = "127.0.0.1"
CONVERSATION = "web"   # one person, one browser: a single conversation

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Junot</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1b2330; --muted:#5b6575; --line:#d6dbe3; --accent:#2753c9; }
  @media (prefers-color-scheme: dark) { :root { --bg:#11151c; --card:#181e27; --ink:#e4e8ef; --muted:#98a2b3; --line:#2d3644; --accent:#7c9bf0; } }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system, "Segoe UI", sans-serif; }
  main { max-width:720px; margin:0 auto; padding:24px 16px; display:grid; gap:12px; }
  h1 { font-size:20px; margin:0; }
  #log { display:grid; gap:10px; }
  .msg { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; white-space:pre-wrap; }
  .you { border-color:var(--accent); }
  .meta { color:var(--muted); font:12px ui-monospace, Menlo, monospace; margin-top:6px; white-space:pre-wrap; }
  form { display:flex; gap:8px; }
  input { flex:1; padding:10px 12px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--ink); font:inherit; }
  button { padding:10px 16px; border-radius:8px; border:0; background:var(--accent); color:#fff; font:inherit; cursor:pointer; }
  button:disabled { opacity:.5; }
</style></head>
<body><main>
  <h1>Junot</h1>
  <div id="log"></div>
  <form id="f"><input id="t" autocomplete="off" placeholder="Message Junot" autofocus><button id="b">Send</button></form>
</main>
<script>
const log = document.getElementById("log"), f = document.getElementById("f"),
      t = document.getElementById("t"), b = document.getElementById("b");
function add(cls, text, meta) {
  const d = document.createElement("div"); d.className = "msg " + cls; d.textContent = text;
  if (meta) { const m = document.createElement("div"); m.className = "meta"; m.textContent = meta; d.appendChild(m); }
  log.appendChild(d); d.scrollIntoView({block: "end"});
}
f.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = t.value.trim(); if (!text) return;
  add("you", text); t.value = ""; b.disabled = true;
  try {
    const r = await fetch("/chat", {method: "POST", headers: {"Content-Type": "application/json"},
                                    body: JSON.stringify({text})});
    const data = await r.json();
    add("junot", data.reply || data.error, [...(data.events || []), data.receipt].filter(Boolean).join("\\n"));
  } catch (err) { add("junot", "Couldn't reach Junot: " + err); }
  b.disabled = false; t.focus();
});
</script></body></html>
"""


def describe(kind: str, event: dict) -> str | None:
    """The same one-liners the terminal prints, for the page to show under a reply."""
    if kind == "gate":
        return f"gate: search {event['query']!r}, {event['hits']} note(s)" if event["retrieve"] else "gate: skip"
    if kind == "skills" and event["matched"]:
        return f"skill: {', '.join(event['matched'])}"
    if kind == "tool":
        return f"tool: {event['name']}({event['arguments']})" + ("" if event["ok"] else " failed")
    if kind == "consolidation":
        return f"learned {len(event['facts'])} note(s)" if not event.get("error") else "learning failed, will retry"
    return None


def receipt(totals: dict) -> str:
    return (f"{totals.get('llm_calls', 0)} llm · {totals.get('tool_calls', 0)} tool · "
            f"{totals.get('input_tokens', 0)} in / {totals.get('output_tokens', 0)} out")


def make_handler(junot):
    """A request handler class bound to this Junot. http.server builds one
    handler object per request from the class, so the Junot travels on it."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data).encode("utf-8"), "application/json")

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/chat":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                text = str(json.loads(self.rfile.read(length) or b"{}").get("text", "")).strip()
            except (ValueError, AttributeError):
                self._json(400, {"error": "send JSON like {\"text\": \"hello\"}"})
                return
            if not text:
                self._json(400, {"error": "the message is empty"})
                return
            events: list[str] = []

            def collect(kind: str, event: dict) -> None:
                line = describe(kind, event)
                if line:
                    events.append(line)

            turn = junot.respond(text, conversation=CONVERSATION, observer=collect)
            self._json(200, {"reply": turn.reply, "events": events, "receipt": receipt(turn.totals),
                             "error": turn.error})

        def log_message(self, format: str, *args) -> None:
            pass   # keep the terminal quiet; the trace has everything

    return Handler


def make_server(junot, port: int, host: str = HOST) -> HTTPServer:
    return HTTPServer((host, port), make_handler(junot))


def main() -> None:
    settings = load_settings()
    port = int(os.getenv("JUNOT_WEB_PORT", "8765"))
    junot = Junot(settings)
    server = make_server(junot, port)
    print(f"Junot is at http://{HOST}:{port}  (this laptop only). Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        junot.close()


if __name__ == "__main__":
    main()
