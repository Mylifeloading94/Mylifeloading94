"""Send a trade message (optionally with a chart) to Telegram.
Usage: notify.py "caption text" [chart.png]
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (loaded from .env if present)."""
import os, sys, json, urllib.request, urllib.parse, uuid, pathlib
env = pathlib.Path(__file__).resolve().parent.parent / ".env"
if env.exists():
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if not tok or not chat: sys.exit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
text = sys.argv[1]; photo = sys.argv[2] if len(sys.argv) > 2 else None
api = f"https://api.telegram.org/bot{tok}/"
if photo:
    b = uuid.uuid4().hex; body = b""
    for k, v in (("chat_id", chat), ("caption", text[:1024])):
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += (f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="chart.png"\r\n'
             f'Content-Type: image/png\r\n\r\n').encode() + open(photo, "rb").read() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(api + "sendPhoto", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
else:
    req = urllib.request.Request(api + "sendMessage", urllib.parse.urlencode({"chat_id": chat, "text": text}).encode())
print(json.load(urllib.request.urlopen(req, timeout=30)).get("ok"))
