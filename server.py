import json
import mimetypes
import os
import csv
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request


HOST = "127.0.0.1"
PORT = 8000
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ADMISSIONS_JSONL_FILE = DATA_DIR / "admission-leads.jsonl"
ADMISSIONS_CSV_FILE = DATA_DIR / "admission-leads.csv"
CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4"

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
            "content": SCHOOL_CONTEXT,
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
                "content": text,
            }
        )

    items.append(
        {
            "role": "user",
            "content": str(message).strip(),
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
    choices = data.get("choices", [])
    if isinstance(choices, list) and len(choices) > 0:
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            content = message.get("content", "")
            if content:
                return str(content).strip()
    return ""


def collapse_whitespace(value):
    return " ".join(str(value or "").split())


def limit_text(value, max_length):
    return collapse_whitespace(value)[:max_length]


def normalize_env_value(value):
    return str(value or "").strip().strip('"').strip("'")


def is_configured_value(value):
    normalized_value = normalize_env_value(value)
    return bool(
        normalized_value
        and not normalized_value.lower().startswith("replace_with_")
        and normalized_value != "your_cloudflare_account_id"
    )


def get_env_value(names):
    for name in names:
        value = normalize_env_value(os.environ.get(name, ""))
        if is_configured_value(value):
            return value
    return ""


def get_cloudflare_d1_config():
    api_token = get_env_value(["CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"])
    account_id = get_env_value(["CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID", "R2_ACCOUNT_ID"])
    database_id = get_env_value(["CLOUDFLARE_D1_DATABASE_ID", "CF_D1_DATABASE_ID", "D1_DATABASE_ID"])
    if not api_token or not account_id or not database_id:
        return None

    return {
        "api_token": api_token,
        "account_id": account_id,
        "database_id": database_id,
    }


def parse_admission_payload(payload):
    record = {
        "studentName": limit_text(payload.get("studentName"), 120),
        "dateOfBirth": limit_text(payload.get("dateOfBirth"), 30),
        "gradeApplyingFor": limit_text(payload.get("gradeApplyingFor"), 60),
        "gender": limit_text(payload.get("gender"), 20),
        "fatherName": limit_text(payload.get("fatherName"), 120),
        "motherName": limit_text(payload.get("motherName"), 120),
        "contactNumber": limit_text(payload.get("contactNumber"), 30),
        "emailAddress": limit_text(payload.get("emailAddress"), 160).lower(),
        "lastSchoolAttended": limit_text(payload.get("lastSchoolAttended"), 160),
        "medicalConditions": limit_text(payload.get("medicalConditions"), 1000),
        "declarationAccepted": bool(payload.get("declarationAccepted")),
    }

    errors = []
    required_fields = [
        ("studentName", "Student name is required."),
        ("dateOfBirth", "Date of birth is required."),
        ("gradeApplyingFor", "Grade is required."),
        ("gender", "Gender is required."),
        ("fatherName", "Father's name is required."),
        ("motherName", "Mother's name is required."),
        ("contactNumber", "Contact number is required."),
        ("emailAddress", "Email address is required."),
    ]
    for field_name, message in required_fields:
        if not record[field_name]:
            errors.append(message)

    phone_digits = "".join(ch for ch in record["contactNumber"] if ch.isdigit())
    if record["contactNumber"] and (len(phone_digits) < 10 or len(phone_digits) > 15):
        errors.append("Contact number must contain 10 to 15 digits.")

    if record["emailAddress"]:
        if "@" not in record["emailAddress"] or "." not in record["emailAddress"].split("@")[-1]:
            errors.append("Please enter a valid email address.")

    if not record["declarationAccepted"]:
        errors.append("Please accept the declaration before submitting.")

    return record, errors


def execute_d1_query(config, sql, params=None):
    payload = {"sql": sql}
    if params is not None:
        payload["params"] = params

    req = request.Request(
        f"{CLOUDFLARE_API_BASE_URL}/accounts/{config['account_id']}/d1/database/{config['database_id']}/query",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_token']}",
        },
        method="POST",
    )

    with request.urlopen(req, timeout=60) as resp:
        raw_response = resp.read().decode("utf-8")
        data = json.loads(raw_response or "{}")

    errors = data.get("errors") or []
    if not isinstance(errors, list):
        errors = []

    if data.get("success") is False or errors:
        detail = "Cloudflare D1 query failed."
        if errors and isinstance(errors[0], dict):
            detail = errors[0].get("message", detail)
        raise RuntimeError(detail)

    return data


def ensure_d1_schema(config):
    execute_d1_query(
        config,
        """
        CREATE TABLE IF NOT EXISTS admission_leads (
            admission_id TEXT PRIMARY KEY,
            submitted_at TEXT NOT NULL,
            student_name TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            grade_applying_for TEXT NOT NULL,
            gender TEXT NOT NULL,
            father_name TEXT NOT NULL,
            mother_name TEXT NOT NULL,
            contact_number TEXT NOT NULL,
            email_address TEXT NOT NULL,
            last_school_attended TEXT,
            medical_conditions TEXT,
            declaration_accepted INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'website'
        );
        CREATE INDEX IF NOT EXISTS idx_admission_leads_submitted_at
        ON admission_leads (submitted_at DESC);
        CREATE INDEX IF NOT EXISTS idx_admission_leads_contact_number
        ON admission_leads (contact_number);
        CREATE INDEX IF NOT EXISTS idx_admission_leads_email_address
        ON admission_leads (email_address);
        """,
    )


def save_admission_to_d1(saved_record):
    config = get_cloudflare_d1_config()
    if not config:
        return False

    ensure_d1_schema(config)
    execute_d1_query(
        config,
        """
        INSERT INTO admission_leads (
            admission_id,
            submitted_at,
            student_name,
            date_of_birth,
            grade_applying_for,
            gender,
            father_name,
            mother_name,
            contact_number,
            email_address,
            last_school_attended,
            medical_conditions,
            declaration_accepted,
            source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            saved_record["admissionId"],
            saved_record["submittedAt"],
            saved_record["studentName"],
            saved_record["dateOfBirth"],
            saved_record["gradeApplyingFor"],
            saved_record["gender"],
            saved_record["fatherName"],
            saved_record["motherName"],
            saved_record["contactNumber"],
            saved_record["emailAddress"],
            saved_record["lastSchoolAttended"],
            saved_record["medicalConditions"],
            "1" if saved_record["declarationAccepted"] else "0",
            "website",
        ],
    )
    return True


def save_admission(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid admission payload.")

    record, errors = parse_admission_payload(payload)
    if errors:
        raise ValueError(json.dumps(errors))

    saved_record = {
        "admissionId": f"ADM-{int(time.time() * 1000)}",
        "submittedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        **record,
    }

    if get_cloudflare_d1_config():
        save_admission_to_d1(saved_record)
        return saved_record

    DATA_DIR.mkdir(exist_ok=True)
    if not ADMISSIONS_CSV_FILE.exists():
        with ADMISSIONS_CSV_FILE.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "admissionId",
                    "submittedAt",
                    "studentName",
                    "dateOfBirth",
                    "gradeApplyingFor",
                    "gender",
                    "fatherName",
                    "motherName",
                    "contactNumber",
                    "emailAddress",
                    "lastSchoolAttended",
                    "medicalConditions",
                ]
            )

    with ADMISSIONS_JSONL_FILE.open("a", encoding="utf-8") as jsonl_file:
        jsonl_file.write(json.dumps(saved_record, ensure_ascii=True) + "\n")

    with ADMISSIONS_CSV_FILE.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                saved_record["admissionId"],
                saved_record["submittedAt"],
                saved_record["studentName"],
                saved_record["dateOfBirth"],
                saved_record["gradeApplyingFor"],
                saved_record["gender"],
                saved_record["fatherName"],
                saved_record["motherName"],
                saved_record["contactNumber"],
                saved_record["emailAddress"],
                saved_record["lastSchoolAttended"],
                saved_record["medicalConditions"],
            ]
        )

    return saved_record


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
        if self.path not in {"/api/chat", "/api/admissions"}:
            self.send_json(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b""

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON body."})
            return

        if self.path == "/api/admissions":
            try:
                saved_record = save_admission(payload)
            except ValueError as exc:
                details = []
                try:
                    details = json.loads(str(exc))
                except json.JSONDecodeError:
                    pass
                self.send_json(
                    400,
                    {
                        "error": "Please review the admission form.",
                        "details": details,
                    },
                )
                return
            except Exception:
                self.send_json(500, {"error": "Unable to save the admission form right now."})
                return

            self.send_json(
                201,
                {
                    "ok": True,
                    "admissionId": saved_record["admissionId"],
                    "submittedAt": saved_record["submittedAt"],
                    "message": "Registration successfully submitted.",
                },
            )
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
            "model": "gpt-4o-mini",
            "messages": build_input(history, message),
        }

        req = request.Request(
            "https://api.openai.com/v1/chat/completions",
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

        if safe_path == DATA_DIR or DATA_DIR in safe_path.parents:
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
