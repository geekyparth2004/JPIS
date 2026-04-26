import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request


HOST = "127.0.0.1"
PORT = 8000
BASE_DIR = Path(__file__).resolve().parent

SCHOOL_CONTEXT = """
You are the parent-support AI assistant for J.P. International School.
Answer in a warm, clear, concise way.
Focus on helping parents with admissions, academics, facilities, fees, timings, contact details, and campus visits.
If exact information is not available, say that politely and ask the parent to contact the school office.
Do not invent fee amounts, policies, dates, or legal claims.
Keep answers short and practical.
""".strip()


def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


def build_input(history, message):
    items = [
        {
            "role": "developer",
            "content": [{"type": "input_text", "text": SCHOOL_CONTEXT}],
        }
    ]

    recent_history = history[-8:] if isinstance(history, list) else []
    for entry in recent_history:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text", "")).strip()
        sender = entry.get("sender")
        if not text or sender not in {"assistant", "user"}:
            continue
        items.append(
            {
                "role": sender,
                "content": [{"type": "input_text", "text": text}],
            }
        )

    items.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": str(message).strip()}],
        }
    )
    return items


def is_api_key_configured(api_key):
    return bool(
        api_key
        and api_key.startswith("sk-")
        and "replace_with_your_new_openai_api_key" not in api_key
    )


def extract_reply_text(data):
    output_text = str(data.get("output_text", "")).strip()
    if output_text:
        return output_text

    output_items = data.get("output", [])
    if not isinstance(output_items, list):
        return ""

    for item in output_items:
        if not isinstance(item, dict):
            continue
        contents = item.get("content", [])
        if not isinstance(contents, list):
            continue
        for content in contents:
            if not isinstance(content, dict):
                continue
            text = str(content.get("text", "")).strip()
            if text:
                return text

    return ""


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "JPISChatServer/1.1"

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self.serve_file("index.html")
            return

        if self.path == "/api/health":
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            self.send_json(
                200,
                {
                    "ok": True,
                    "configured": is_api_key_configured(api_key),
                },
            )
            return

        path = self.path.lstrip("/")
        self.serve_file(path)

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_json(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b""

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON body."})
            return

        message = str(payload.get("message", "")).strip()
        history = payload.get("history", [])

        if not message:
            self.send_json(400, {"error": "Message is required."})
            return

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not is_api_key_configured(api_key):
            self.send_json(500, {"error": "Missing OPENAI_API_KEY in .env."})
            return

        request_body = {
            "model": "gpt-4.1-mini",
            "input": build_input(history, message),
        }

        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=60) as resp:
                raw_response = resp.read().decode("utf-8")
                data = json.loads(raw_response)
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                error_json = json.loads(error_body)
                message_text = error_json.get("error", {}).get("message", "OpenAI request failed.")
            except json.JSONDecodeError:
                message_text = "OpenAI request failed."
            self.send_json(exc.code, {"error": message_text})
            return
        except Exception:
            self.send_json(500, {"error": "Server error while contacting OpenAI."})
            return

        self.send_json(
            200,
            {
                "reply": extract_reply_text(data)
                or "I am here to help with school-related questions."
            },
        )

    def serve_file(self, relative_path):
        safe_path = (BASE_DIR / relative_path).resolve()
        if BASE_DIR not in safe_path.parents and safe_path != BASE_DIR:
            self.send_json(403, {"error": "Forbidden"})
            return

        if not safe_path.exists() or not safe_path.is_file():
            self.send_json(404, {"error": "File not found"})
            return

        content_type, _ = mimetypes.guess_type(str(safe_path))
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.end_headers()
        self.wfile.write(safe_path.read_bytes())

    def send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), ChatHandler)
    print(f"JPIS server running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
