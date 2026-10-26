"""Step 9: the gateways. These test the web and Telegram front ends against a
fake Junot, so no model, no network and no Telegram account is needed.

    uv run pytest tests/test_step09_gateways.py -v
"""

from __future__ import annotations

import ast
import json
import threading
import urllib.request
from pathlib import Path

from junot import telegram, web
from junot.app import Turn

JUNOT = Path(__file__).resolve().parents[1] / "junot"


class FakeJunot:
    """Stands in for Junot.respond(): records what it was asked."""

    def __init__(self, reply: str = "Hello, General."):
        self.reply = reply
        self.asked: list[tuple[str, str]] = []

    def respond(self, text, conversation="cli", observer=None):
        self.asked.append((text, conversation))
        if observer:
            observer("gate", {"retrieve": True, "query": "brother", "hits": 1})
            observer("tool", {"name": "get_time", "arguments": "{}", "ok": True})
        return Turn(self.reply, {"llm_calls": 1, "tool_calls": 1, "input_tokens": 700, "output_tokens": 40})


# ---- the boundary: gateways talk to Junot, never to its parts --------------------

def _junot_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("junot"):
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names if a.name.startswith("junot"))
    return names


def test_gateways_only_import_the_app_and_config():
    """Step 9's whole claim: a front end needs nothing from the loop, the
    session, memory, the gate or the tools. If one imports them, the wiring
    has leaked out of app.py again."""
    for gateway in ("__main__.py", "web.py", "telegram.py"):
        assert _junot_imports(JUNOT / gateway) <= {"junot.app", "junot.config"}, gateway


# ---- web ---------------------------------------------------------------------------

def _serve(junot):
    server = web.make_server(junot, port=0)   # port 0: the OS picks a free one
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url: str, body: bytes):
    request = urllib.request.Request(url + "/chat", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_the_web_gateway_listens_on_this_laptop_only():
    server = web.make_server(FakeJunot(), port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_the_page_is_served():
    server, url = _serve(FakeJunot())
    try:
        with urllib.request.urlopen(url + "/") as response:
            page = response.read().decode()
        assert "<form" in page and "/chat" in page
    finally:
        server.shutdown()
        server.server_close()


def test_a_chat_message_reaches_junot_and_the_reply_comes_back():
    junot = FakeJunot()
    server, url = _serve(junot)
    try:
        status, data = _post(url, json.dumps({"text": "Who is my brother?"}).encode())
        assert status == 200
        assert data["reply"] == "Hello, General."
        assert junot.asked == [("Who is my brother?", "web")]
        assert "gate: search 'brother', 1 note(s)" in data["events"]
        assert "tool: get_time({})" in data["events"]
        assert data["receipt"] == "1 llm · 1 tool · 700 in / 40 out"
    finally:
        server.shutdown()
        server.server_close()


def test_bad_or_empty_messages_are_refused_without_calling_junot():
    junot = FakeJunot()
    server, url = _serve(junot)
    try:
        assert _post(url, b"not json")[0] == 400
        assert _post(url, json.dumps({"text": "   "}).encode())[0] == 400
        assert junot.asked == []
    finally:
        server.shutdown()
        server.server_close()


# ---- telegram -------------------------------------------------------------------------

class FakeTelegram:
    """api(method, params) as Telegram would answer it, recording every call."""

    def __init__(self, updates=None, fail=False):
        self.updates = updates or []
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, params):
        self.calls.append((method, params))
        if method == "getUpdates":
            if self.fail:
                raise RuntimeError("Telegram getUpdates failed: timed out")
            return {"ok": True, "result": self.updates}
        return {"ok": True}

    def sent(self) -> list[str]:
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def _update(update_id: int, text: str, user: int = 42, chat: int = 42) -> dict:
    return {"update_id": update_id, "message": {"text": text, "chat": {"id": chat}, "from": {"id": user}}}


def test_an_allowed_user_talks_to_junot_in_their_own_conversation():
    junot, api = FakeJunot(), FakeTelegram()
    telegram.handle(_update(1, "Who is my brother?"), junot, api, allowed={42})
    assert junot.asked == [("Who is my brother?", "telegram:42")]
    assert api.sent() == ["Hello, General."]


def test_a_stranger_is_refused_and_never_reaches_junot():
    """A bot is public. Without this, anyone who finds it reads your notes."""
    junot, api = FakeJunot(), FakeTelegram()
    telegram.handle(_update(1, "What's in your notes?", user=999, chat=999), junot, api, allowed={42})
    assert junot.asked == []
    [refusal] = api.sent()
    assert "999" in refusal, "tell them their id, so the owner can allow themselves"


def test_an_empty_allow_list_refuses_everyone():
    junot, api = FakeJunot(), FakeTelegram()
    telegram.handle(_update(1, "hi"), junot, api, allowed=set())
    assert junot.asked == []


def test_start_is_answered_without_the_model():
    junot, api = FakeJunot(), FakeTelegram()
    telegram.handle(_update(1, "/start"), junot, api, allowed={42})
    assert junot.asked == [] and len(api.sent()) == 1


def test_a_message_without_text_is_ignored():
    junot, api = FakeJunot(), FakeTelegram()
    telegram.handle({"update_id": 1, "message": {"photo": [], "chat": {"id": 42}, "from": {"id": 42}}},
                    junot, api, allowed={42})
    assert junot.asked == [] and api.sent() == []


def test_a_long_reply_is_split_into_telegram_sized_messages():
    junot, api = FakeJunot(reply="line\n" * 2000), FakeTelegram()
    telegram.handle(_update(1, "go"), junot, api, allowed={42})
    assert len(api.sent()) > 1
    assert all(len(piece) <= telegram.LIMIT for piece in api.sent())


def test_polling_handles_each_update_and_moves_the_offset_past_it():
    junot = FakeJunot()
    api = FakeTelegram(updates=[_update(7, "one"), _update(8, "two")])
    assert telegram.poll_once(api, junot, {42}, offset=0) == 9
    assert [text for text, _ in junot.asked] == ["one", "two"]


def test_a_network_failure_keeps_the_offset_and_doesnt_crash():
    assert telegram.poll_once(FakeTelegram(fail=True), FakeJunot(), {42}, offset=5) == 5


def test_the_allow_list_reads_comma_separated_ids():
    assert telegram.allowed_ids("123, 456,abc,") == {123, 456}
    assert telegram.allowed_ids("") == set()


# ---- speed: one kept-open connection, and "typing" off the critical path ------------
# Measured live: a fresh HTTPS request to Telegram took ~1.7 s, and a reply made
# three in a row. These pin the two fixes.

import http.client
import time

TOKEN = "123456:SECRET-TOKEN"


class FakeConnection:
    """Stands in for http.client.HTTPSConnection."""

    def __init__(self, fail_first: bool = False, status: int = 200):
        self.fail_first = fail_first
        self.status = status
        self.paths: list[str] = []
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.paths.append(path)

    def getresponse(self):
        if self.fail_first:
            self.fail_first = False
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        status = self.status

        class Response:
            def read(self):
                return b'{"ok": true, "result": []}'
        response = Response()
        response.status = status
        return response

    def close(self):
        self.closed = True


def test_one_connection_is_reused_for_every_call():
    opened = []
    api = telegram.TelegramApi(TOKEN, connect=lambda: opened.append(FakeConnection()) or opened[-1])
    api("getUpdates", {"offset": 0})
    api("sendMessage", {"chat_id": 42, "text": "hi"})
    api("sendMessage", {"chat_id": 42, "text": "again"})
    assert len(opened) == 1, "the TCP and TLS handshakes are paid once, not per call"
    assert opened[0].paths == [f"/bot{TOKEN}/getUpdates", f"/bot{TOKEN}/sendMessage", f"/bot{TOKEN}/sendMessage"]


def test_a_stale_connection_is_replaced_and_the_call_still_succeeds():
    """Telegram closes idle connections. The first request after that fails;
    one retry on a fresh connection makes it invisible."""
    connections = [FakeConnection(fail_first=True), FakeConnection()]
    api = telegram.TelegramApi(TOKEN, connect=lambda: connections.pop(0))
    assert api("sendMessage", {"chat_id": 42, "text": "hi"}) == {"ok": True, "result": []}
    assert api.connections_opened == 2


def test_errors_never_show_the_token():
    class Down:
        def request(self, *args, **kwargs):
            raise ConnectionRefusedError(f"could not reach /bot{TOKEN}/sendMessage")

        def close(self):
            pass
    api = telegram.TelegramApi(TOKEN, connect=Down)
    try:
        api("sendMessage", {"chat_id": 42, "text": "hi"})
        raise AssertionError("should have failed")
    except RuntimeError as exc:
        assert "sendMessage" in str(exc)
        assert TOKEN not in str(exc) and "SECRET" not in str(exc)


def test_an_http_error_names_the_method_and_status_not_the_token():
    api = telegram.TelegramApi(TOKEN, connect=lambda: FakeConnection(status=401))
    try:
        api("getUpdates", {})
        raise AssertionError("should have failed")
    except RuntimeError as exc:
        assert "getUpdates" in str(exc) and "401" in str(exc) and "SECRET" not in str(exc)


def test_typing_never_delays_the_turn():
    """sendChatAction used to block ~1.7 s before Junot even started."""
    class SlowTyping(FakeTelegram):
        def __call__(self, method, params):
            if method == "sendChatAction":
                time.sleep(0.5)
            return super().__call__(method, params)

    started = []

    class TimedJunot(FakeJunot):
        def respond(self, text, conversation="cli", observer=None):
            started.append(time.perf_counter())
            return super().respond(text, conversation, observer)

    api, junot = SlowTyping(), TimedJunot()
    begin = time.perf_counter()
    telegram.handle(_update(1, "hi"), junot, api, allowed={42})
    assert started[0] - begin < 0.2, "Junot starts thinking at once, typing or not"
    assert api.sent() == ["Hello, General."]


def test_a_failed_typing_call_doesnt_stop_the_reply():
    class NoTyping(FakeTelegram):
        def __call__(self, method, params):
            if method == "sendChatAction":
                raise RuntimeError("Telegram sendChatAction failed: timeout")
            return super().__call__(method, params)

    api = NoTyping()
    telegram.handle(_update(1, "hi"), FakeJunot(), api, allowed={42})
    assert api.sent() == ["Hello, General."]
