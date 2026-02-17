from __future__ import annotations

import base64
import json
import os
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

MESSAGES_ROOT = Path(os.getenv("OPENACK_MESSAGES_ROOT", "/messages"))
PEOPLE_FILE = Path(os.getenv("OPENACK_PEOPLE_FILE", "/var/lib/openack/people.yml"))
AGENT_IDS_FILE = Path(os.getenv("OPENACK_AGENT_IDS_FILE", "/var/lib/openack/agent_ids.yml"))


def sanitize_agent_name(agent: str) -> str:
    safe = agent.strip().lower()
    if not safe:
        raise ValueError(f"Invalid agent name: {agent!r}")
    if any(not (ch.isalnum() or ch in {"-", "_"}) for ch in safe):
        raise ValueError(f"Invalid agent name: {agent!r}")
    return safe


def load_valid_people() -> set[str]:
    if not PEOPLE_FILE.exists():
        raise ValueError(f"People directory file not found: {PEOPLE_FILE}")

    payload = yaml.safe_load(PEOPLE_FILE.read_text(encoding="utf-8")) or {}
    raw_people = payload.get("people", []) if isinstance(payload, dict) else []
    people = {str(name).strip().lower() for name in raw_people if str(name).strip()}

    if not people:
        raise ValueError(f"No valid people found in {PEOPLE_FILE}")

    return people


def load_agent_id_map() -> dict[str, str]:
    if not AGENT_IDS_FILE.exists():
        raise ValueError(f"Agent ID file not found: {AGENT_IDS_FILE}")

    payload = yaml.safe_load(AGENT_IDS_FILE.read_text(encoding="utf-8")) or {}
    raw_map = payload.get("id", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw_map, dict) or not raw_map:
        raise ValueError(f"No valid id mapping found in {AGENT_IDS_FILE}")

    valid_people = load_valid_people()
    resolved: dict[str, str] = {}
    for key, value in raw_map.items():
        agent_id = str(key).strip()
        if not agent_id:
            continue

        agent_name = sanitize_agent_name(str(value))
        if agent_name not in valid_people:
            raise ValueError(f"Agent ID maps to unknown person: {agent_name}")
        resolved[agent_id] = agent_name

    if not resolved:
        raise ValueError(f"No valid id mapping found in {AGENT_IDS_FILE}")

    return resolved


def _parse_message_file(message_file: Path) -> tuple[dict[str, str], str, list[Path]]:
    lines = message_file.read_text(encoding="utf-8").splitlines()
    if "=== HEADER ===" not in lines or "=== FOOTER ===" not in lines:
        raise ValueError(f"Malformed message file: {message_file}")

    header_start = lines.index("=== HEADER ===") + 1
    footer_start = len(lines) - 1 - lines[::-1].index("=== FOOTER ===")

    header: dict[str, str] = {}
    body_start = header_start
    for idx in range(header_start, footer_start):
        line = lines[idx].strip()
        if not line:
            body_start = idx + 1
            break
        if ":" in line:
            key, value = line.split(":", 1)
            header[key.strip()] = value.strip()

    message_text = "\n".join(lines[body_start:footer_start]).strip()

    attachment_paths: list[Path] = []
    for line in lines[footer_start + 1 :]:
        trimmed = line.strip()
        if trimmed.startswith("- "):
            raw = trimmed[2:].strip()
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = message_file.parent / candidate
            attachment_paths.append(candidate)

    return header, message_text, attachment_paths


def _archive_processed_message(message_file: Path, attachments: list[Path]) -> None:
    done_dir = message_file.parent.parent / "done"
    done_dir.mkdir(parents=True, exist_ok=True)

    zip_path = done_dir / f"{message_file.stem}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if message_file.exists():
            archive.write(message_file, arcname=message_file.name)
        for attachment in attachments:
            if attachment.exists():
                archive.write(attachment, arcname=attachment.name)

    if message_file.exists():
        message_file.unlink()
    for attachment in attachments:
        if attachment.exists():
            attachment.unlink()


def fetch_messages_by_id(agent_id: str) -> list[dict]:
    lookup = load_agent_id_map()
    mapped_agent = lookup.get(agent_id.strip())
    if not mapped_agent:
        raise ValueError("Unknown agent id")

    inbox_dir = MESSAGES_ROOT / mapped_agent / "inbox"
    if not inbox_dir.exists():
        return []

    messages: list[dict] = []
    for message_file in sorted(inbox_dir.glob("*.md")):
        header, message_text, attachment_paths = _parse_message_file(message_file)

        attachments = []
        for attachment in attachment_paths:
            if attachment.exists():
                encoded = base64.b64encode(attachment.read_bytes()).decode("utf-8")
                attachments.append({"file": attachment.name, "content": encoded})

        messages.append(
            {
                "from": header.get("from", ""),
                "to": header.get("to", mapped_agent),
                "sent_at": header.get("sent_at", ""),
                "message": message_text,
                "attachments": attachments,
            }
        )

        _archive_processed_message(message_file, attachment_paths)

    return messages


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "OpenAck Fetch API",
        "version": "1.0.0",
        "description": "Fetch API for agent inbox consumption using private agent IDs.",
    },
    "paths": {
        "/messages": {
            "get": {
                "summary": "Fetch and consume inbox messages using an agent ID",
                "parameters": [
                    {
                        "name": "id",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Message list (empty array when no messages)"},
                    "400": {"description": "Bad request"},
                    "500": {"description": "Server error"},
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
    <title>OpenAck Fetch API Docs</title>
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


class FetchHandler(BaseHTTPRequestHandler):
    def _send_text(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, code: int, data: object) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/howto":
            self._send_json(HTTPStatus.OK, OPENAPI_SPEC)
            return
        if path == "/docs":
            self._send_text(HTTPStatus.OK, SWAGGER_HTML, "text/html; charset=utf-8")
            return
        if path == "/messages":
            agent_id = parse_qs(parsed_url.query).get("id", [""])[0]
            if not agent_id.strip():
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing id query parameter"})
                return
            try:
                messages = fetch_messages_by_id(agent_id)
            except ValueError as err:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(err)})
                return
            except Exception as err:  # noqa: BLE001
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Unexpected server error: {err}"})
                return

            self._send_json(HTTPStatus.OK, messages)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})


def run_server(host: str = "0.0.0.0", port: int = 9090) -> None:
    server = ThreadingHTTPServer((host, port), FetchHandler)
    print(f"Fetch API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    host = os.environ.get("OPENACK_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENACK_PORT", "9090"))
    run_server(host=host, port=port)
