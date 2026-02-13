from __future__ import annotations

import json
import os
from collections import defaultdict
from email.parser import BytesParser
from email.policy import default
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent
MESSAGES_ROOT = Path(os.getenv("OPENACK_MESSAGES_ROOT", "/messages"))
LOG_PATH = BASE_DIR / "transactions.log"
PEOPLE_FILE = Path(os.getenv("OPENACK_PEOPLE_FILE", "/var/lib/openack/people.yml"))


def load_valid_people() -> set[str]:
    if not PEOPLE_FILE.exists():
        raise ValueError(f"People directory file not found: {PEOPLE_FILE}")

    people: set[str] = set()
    for raw_line in PEOPLE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("-"):
            name = line[1:].strip().lower()
            if name:
                people.add(name)

    if not people:
        raise ValueError(f"No valid people found in {PEOPLE_FILE}")

    return people


def sanitize_agent_name(agent: str) -> str:
    safe = agent.strip().lower()
    if not safe:
        raise ValueError(f"Invalid agent name: {agent!r}")
    if any(not (ch.isalnum() or ch in {"-", "_"}) for ch in safe):
        raise ValueError(f"Invalid agent name: {agent!r}")
    return safe


def ensure_inbox(recipient: str) -> Path:
    inbox_dir = MESSAGES_ROOT / recipient / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    return inbox_dir


def write_transaction_log(sender: str, recipient: str, sent_at: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"from={sender},to={recipient},datetime={sent_at}\n")


def make_message_filename(message_uuid: str, sent_at: str) -> str:
    timestamp = sent_at.replace("+00:00", "Z")
    return f"{timestamp}-{message_uuid}.md"


def write_message(sender: str, recipient: str, message: str, files: list[tuple[str, bytes]], sent_at: str) -> dict:
    message_uuid = uuid4().hex
    inbox_dir = ensure_inbox(recipient)

    attachment_paths: list[str] = []
    for index, (original_name, content) in enumerate(files, start=1):
        ext = Path(original_name or "attachment.bin").suffix
        attachment_name = f"{message_uuid}-attachment{index}{ext}"
        target = inbox_dir / attachment_name
        target.write_bytes(content)
        attachment_paths.append(str(target))

    header = [
        "=== HEADER ===",
        f"from: {sender}",
        f"to: {recipient}",
        f"sent_at: {sent_at}",
        "",
    ]

    footer = ["", "=== FOOTER ==="]
    if attachment_paths:
        footer.append("attachments:")
        footer.extend(f"- {path}" for path in attachment_paths)
    else:
        footer.append(f"reply_url: /messages?from={recipient}&to={sender}")

    message_file = inbox_dir / make_message_filename(message_uuid, sent_at)
    message_file.write_text("\n".join(header + [message.strip()] + footer) + "\n", encoding="utf-8")

    write_transaction_log(sender, recipient, sent_at)

    return {
        "recipient": recipient,
        "message_file": str(message_file),
        "attachments": attachment_paths,
    }


def handle_send_message(sender: str, recipients: list[str], message: str, files: list[tuple[str, bytes]]) -> dict:
    valid_people = load_valid_people()

    clean_sender = sanitize_agent_name(sender)
    clean_recipients = [sanitize_agent_name(recipient) for recipient in recipients]

    if clean_sender not in valid_people:
        raise ValueError(f"Sender is not in directory: {clean_sender}")

    if not clean_recipients:
        raise ValueError("At least one recipient is required")

    invalid_recipients = [person for person in clean_recipients if person not in valid_people]
    if invalid_recipients:
        raise ValueError(f"Recipient(s) not in directory: {', '.join(invalid_recipients)}")

    if not message.strip():
        raise ValueError("Message body must not be empty")

    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    deliveries = [write_message(clean_sender, recipient, message, files, sent_at) for recipient in clean_recipients]

    return {
        "status": "ok",
        "from": clean_sender,
        "to": clean_recipients,
        "sent_at": sent_at,
        "deliveries": deliveries,
    }


def parse_multipart_form_data(content_type: str, body: bytes) -> tuple[str, list[str], str, list[tuple[str, bytes]]]:
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )

    if not message.is_multipart():
        raise ValueError("Invalid multipart form payload")

    fields: dict[str, list[str]] = defaultdict(list)
    files: list[tuple[str, bytes]] = []

    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue

        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append((filename, payload))
        else:
            fields[name].append(part.get_content())

    sender = fields.get("from", [""])[0]
    recipients = fields.get("to", [])
    text_message = fields.get("message", [""])[0]

    return sender, recipients, text_message, files


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "OpenAck API",
        "version": "1.3.0",
        "description": "File-based message middleware for agent-to-agent communication.",
    },
    "paths": {
        "/messages": {
            "post": {
                "summary": "Send a message to one or many recipients",
                "description": "Writes message files and optional attachments into /messages/<recipient>/inbox.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["from", "to", "message"],
                                "properties": {
                                    "from": {"type": "string"},
                                    "to": {"type": "array", "items": {"type": "string"}},
                                    "message": {"type": "string"},
                                    "files": {
                                        "type": "array",
                                        "items": {"type": "string", "format": "binary"},
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Message delivered"},
                    "400": {"description": "Bad request"},
                    "500": {"description": "Server error"},
                },
            }
        },
        "/directory": {
            "get": {
                "summary": "Show valid people directory",
                "responses": {
                    "200": {"description": "Directory list"},
                    "400": {"description": "Directory file missing/invalid"},
                },
            }
        },
        "/howto": {
            "get": {
                "summary": "OpenAPI document endpoint (JSON)",
                "responses": {"200": {"description": "OpenAPI spec"}},
            }
        },
        "/docs": {
            "get": {
                "summary": "Swagger UI",
                "responses": {"200": {"description": "Swagger UI page"}},
            }
        },
    },
}

SWAGGER_HTML = """<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <title>OpenAck API Docs</title>
    <link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\" />
  </head>
  <body>
    <div id=\"swagger-ui\"></div>
    <script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: '/howto',
        dom_id: '#swagger-ui'
      });
    </script>
  </body>
</html>
"""


class MessageHandler(BaseHTTPRequestHandler):
    def _send_text(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, code: int, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/howto":
            self._send_json(HTTPStatus.OK, OPENAPI_SPEC)
            return
        if path == "/docs":
            self._send_text(HTTPStatus.OK, SWAGGER_HTML, "text/html; charset=utf-8")
            return
        if path == "/directory":
            try:
                people = sorted(load_valid_people())
            except ValueError as err:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
                return
            self._send_json(HTTPStatus.OK, {"people": people, "count": len(people)})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/messages":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(length)

        try:
            if content_type.startswith("multipart/form-data"):
                sender, recipients, message, files = parse_multipart_form_data(content_type, request_body)
            else:
                parsed = parse_qs(request_body.decode("utf-8"))
                sender = parsed.get("from", [""])[0]
                message = parsed.get("message", [""])[0]
                recipients = parsed.get("to", [])
                files = []

            result = handle_send_message(sender, recipients, message, files)
        except ValueError as err:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
            return
        except Exception as err:  # noqa: BLE001
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Unexpected server error: {err}"})
            return

        self._send_json(HTTPStatus.OK, result)


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), MessageHandler)
    print(f"Server listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    host = os.environ.get("OPENACK_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENACK_PORT", "8080"))
    run_server(host=host, port=port)
