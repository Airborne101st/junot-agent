"""Talk to Junot from your phone:  uv run python -m junot.telegram

The Telegram gateway. It asks Telegram for new messages (long polling: one
request that waits up to 30 seconds for something to arrive), calls
Junot.respond() for each, and sends the reply back. Telegram's Bot API is
plain HTTPS and JSON, so the standard library is enough: no dependency.

**Speed.** Measured from a laptop in India, a fresh HTTPS request to Telegram
cost about 1.7 s: a new TCP connection and TLS handshake every time, to
servers far away. A reply took three of them in a row (typing, the reply,
the next poll), so Telegram felt ~3 s slower than the web page, though
Junot's own turn took the same time. Two fixes: one connection kept open and
reused for every call (TelegramApi), and the "typing" indicator sent from a
background thread, so it never delays the turn.

**Who may talk to it.** A bot is public: anyone who finds its name can
message it, and Junot would answer from your notes. So only Telegram user
ids listed in JUNOT_TELEGRAM_ALLOWED reach Junot. Anyone else gets a refusal
that tells them their id, and nothing else; their message never reaches the
model, the trace or the notes.

Messages you send this way pass through Telegram's servers. The web gateway
keeps everything on your laptop; this one doesn't. That's the trade for
being able to use it from your phone.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from collections.abc import Callable

from junot.app import Junot
from junot.config import load_dotenv, load_settings

HOST = "api.telegram.org"
LIMIT = 4096          # Telegram's maximum message length
POLL_SECONDS = 30

Api = Callable[[str, dict], dict]   # api(method, params) -> Telegram's JSON reply


class TelegramApi:
    """Telegram's Bot API over ONE kept-open HTTPS connection.

    urllib opens a new connection per request and pays the TCP and TLS
    handshakes every time (~1.7 s each, measured). Keeping one connection
    open pays them once; every later call is about one round trip.

    A kept-open connection can go stale: the server closes it after a while
    idle, and the next request fails. So a failed request is retried once on
    a fresh connection before it counts as an error.

    The token is part of every request path, so it is never printed: errors
    name the method and the problem, nothing else. A lock keeps two threads
    (the "typing" sender and the main loop) from using the connection at once.
    """

    def __init__(self, token: str, connect: Callable[[], http.client.HTTPConnection] | None = None):
        self._token = token
        self._connect = connect or (lambda: http.client.HTTPSConnection(HOST, timeout=POLL_SECONDS + 10))
        self._conn = None
        self._lock = threading.Lock()
        self.connections_opened = 0   # for tests, and for curiosity

    def _send(self, method: str, body: bytes) -> tuple[int, bytes]:
        if self._conn is None:
            self._conn = self._connect()
            self.connections_opened += 1
        self._conn.request("POST", f"/bot{self._token}/{method}", body=body,
                           headers={"Content-Type": "application/json"})
        response = self._conn.getresponse()
        return response.status, response.read()   # read it all, or the connection can't be reused

    def _drop(self) -> None:
        if self._conn is not None:
            self._conn.close()
        self._conn = None

    def __call__(self, method: str, params: dict) -> dict:
        body = json.dumps(params).encode("utf-8")
        with self._lock:
            for attempt in (1, 2):
                try:
                    status, data = self._send(method, body)
                    break
                except (http.client.HTTPException, OSError) as exc:
                    self._drop()   # stale or broken: the next attempt opens a fresh one
                    if attempt == 2:
                        raise RuntimeError(f"Telegram {method} failed: {type(exc).__name__}") from None
        if status != 200:
            raise RuntimeError(f"Telegram {method} failed with HTTP {status}")
        return json.loads(data)


def make_api(token: str) -> Api:
    return TelegramApi(token)


def _quietly(api: Api, method: str, params: dict) -> None:
    """For calls nobody waits on: a failure here must never matter."""
    try:
        api(method, params)
    except Exception:
        pass


def allowed_ids(value: str) -> set[int]:
    """"123, 456" -> {123, 456}. Anything that isn't a number is ignored."""
    return {int(part) for part in value.replace(" ", "").split(",") if part.lstrip("-").isdigit()}


def chunks(text: str, size: int = LIMIT) -> list[str]:
    """Split a long reply into pieces Telegram accepts, at line breaks where possible."""
    pieces, rest = [], text or "(no reply)"
    while len(rest) > size:
        cut = rest.rfind("\n", 0, size)
        cut = cut if cut > 0 else size
        pieces.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    pieces.append(rest)
    return pieces


def send(api: Api, chat_id: int, text: str) -> None:
    for piece in chunks(text):
        api("sendMessage", {"chat_id": chat_id, "text": piece})


def handle(update: dict, junot, api: Api, allowed: set[int]) -> None:
    """One incoming update. Only text messages from allowed users reach Junot."""
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    user_id = (message.get("from") or {}).get("id")
    if not text or chat_id is None:
        return   # a photo, a sticker, an edit: nothing to answer
    if user_id not in allowed:
        send(api, chat_id, f"Sorry, this Junot only talks to its owner. Your Telegram id is {user_id}; "
                           "if this is your bot, add it to JUNOT_TELEGRAM_ALLOWED in .env and restart.")
        return
    if text == "/start":
        send(api, chat_id, "Junot here. Send me a message.")
        return
    # "typing…" on the phone, sent in the background: it used to block for
    # ~1.7 s before Junot even started, which made the bot slower to look faster.
    threading.Thread(target=_quietly, args=(api, "sendChatAction", {"chat_id": chat_id, "action": "typing"}),
                     daemon=True).start()
    turn = junot.respond(text, conversation=f"telegram:{chat_id}")
    send(api, chat_id, turn.reply)


def poll_once(api: Api, junot, allowed: set[int], offset: int) -> int:
    """Fetch and handle one batch of updates. Returns the next offset. A
    network failure is reported and leaves the offset as it was, so nothing
    is skipped; the caller just tries again."""
    try:
        data = api("getUpdates", {"offset": offset, "timeout": POLL_SECONDS})
    except Exception as exc:
        print(f"  [telegram] {exc}; retrying")
        return offset
    for update in data.get("result", []):
        # Confirm each update before handling it: offset = last id + 1 tells
        # Telegram not to send it again, even if handling it crashes.
        offset = max(offset, update["update_id"] + 1)
        try:
            handle(update, junot, api, allowed)
        except Exception as exc:
            print(f"  [telegram] could not handle update {update['update_id']}: {exc}")
    return offset


def main() -> None:
    load_dotenv()
    token = os.getenv("JUNOT_TELEGRAM_TOKEN", "")
    if not token:
        raise SystemExit("JUNOT_TELEGRAM_TOKEN is not set. Create a bot with @BotFather and put its token in .env.")
    allowed = allowed_ids(os.getenv("JUNOT_TELEGRAM_ALLOWED", ""))
    if not allowed:
        print("JUNOT_TELEGRAM_ALLOWED is empty: everyone is refused. Message the bot once to learn your id.")
    settings = load_settings()
    junot = Junot(settings)
    api = make_api(token)
    print(f"Junot is on Telegram, for {len(allowed)} allowed user(s). Ctrl-C to stop.")
    offset = 0
    try:
        while True:
            next_offset = poll_once(api, junot, allowed, offset)
            if next_offset == offset:
                time.sleep(1)   # nothing new, or Telegram unreachable: don't spin
            offset = next_offset
    except KeyboardInterrupt:
        print()
    finally:
        junot.close()


if __name__ == "__main__":
    main()
