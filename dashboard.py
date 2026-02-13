from __future__ import annotations

import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml
from markdownify import markdownify as html_to_markdown
from streamlit_quill import st_quill

from app import LOG_PATH, MESSAGES_ROOT, PEOPLE_FILE, handle_send_message

HEADER_MARKER = "=== HEADER ==="
FOOTER_MARKER = "=== FOOTER ==="
ADMIN_USER = "admin"


@dataclass
class MessageRecord:
    message_id: str
    location: str
    is_new: bool
    sent_at: str
    sender: str
    recipient: str
    preview: str
    attachments_count: int


@dataclass
class MessageDetails:
    sent_at: str
    sender: str
    recipient: str
    body: str
    attachments: list[str]


def apply_ui_theme(theme_mode: str) -> None:
    st.markdown(
        """
        <style>
          [data-testid="stToolbar"] { display: none !important; }
          button[title="Deploy this app"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if theme_mode == "Light":
        st.markdown("<style>.stApp { background-color: #f8fafc; color: #111827; }</style>", unsafe_allow_html=True)
    elif theme_mode == "Dark":
        st.markdown("<style>.stApp { background-color: #0f172a; color: #e5e7eb; }</style>", unsafe_allow_html=True)


def read_people() -> list[str]:
    if not PEOPLE_FILE.exists():
        return []
    data = yaml.safe_load(PEOPLE_FILE.read_text(encoding="utf-8")) or {}
    raw_people = data.get("people", [])
    return sorted({str(person).strip().lower() for person in raw_people if str(person).strip()})


def write_people(people: list[str]) -> list[str]:
    normalized = sorted({person.strip().lower() for person in people if person.strip()})
    PEOPLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PEOPLE_FILE.write_text(yaml.safe_dump({"people": normalized}, sort_keys=False), encoding="utf-8")
    return normalized


def ensure_admin_in_people() -> list[str]:
    people = read_people()
    if ADMIN_USER in people:
        return people
    return write_people(people + [ADMIN_USER])


def parse_message_text(text: str) -> MessageDetails:
    sender, recipient, sent_at = "", "", ""
    attachments: list[str] = []

    header_block = text.split(HEADER_MARKER, maxsplit=1)[1] if HEADER_MARKER in text else text
    body_block, footer_block = header_block.split(FOOTER_MARKER, maxsplit=1) if FOOTER_MARKER in header_block else (header_block, "")

    body_lines: list[str] = []
    for line in body_block.strip("\n").splitlines():
        stripped = line.strip()
        if stripped.startswith("from:"):
            sender = stripped.split(":", maxsplit=1)[1].strip()
        elif stripped.startswith("to:"):
            recipient = stripped.split(":", maxsplit=1)[1].strip()
        elif stripped.startswith("sent_at:"):
            sent_at = stripped.split(":", maxsplit=1)[1].strip()
        elif not re.match(r"^(from|to|sent_at):", stripped):
            body_lines.append(line)

    for line in footer_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            attachments.append(stripped[1:].strip())

    return MessageDetails(sent_at=sent_at, sender=sender, recipient=recipient, body="\n".join(body_lines).strip(), attachments=attachments)


def _message_preview(text: str, limit: int = 80) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else f"{clean[: limit - 3]}..."


def _parse_iso_dt(raw: str) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return raw


def resolve_archived_attachment_name(archive_names: list[str], attachment: str, message_member: str) -> str | None:
    archive_set = set(archive_names)
    attachment_path = Path(attachment)

    candidates = [attachment]
    candidates.append(attachment.lstrip("/"))

    if "/messages/" in attachment:
        _, _, suffix = attachment.partition("/messages/")
        candidates.append(suffix)

    candidates.append(attachment_path.name)

    message_parent = Path(message_member).parent
    if str(message_parent) not in {"", "."}:
        candidates.append((message_parent / attachment_path.name).as_posix())

    for candidate in candidates:
        if candidate in archive_set:
            return candidate

    return None


def scan_messages() -> tuple[list[MessageRecord], dict[str, MessageDetails]]:
    records: list[MessageRecord] = []
    detail_cache: dict[str, MessageDetails] = {}

    if not MESSAGES_ROOT.exists():
        return records, detail_cache

    for person_dir in sorted(path for path in MESSAGES_ROOT.iterdir() if path.is_dir()):
        inbox = person_dir / "inbox"
        if inbox.exists():
            for msg_path in sorted(inbox.glob("*.md"), reverse=True):
                details = parse_message_text(msg_path.read_text(encoding="utf-8"))
                message_id = f"inbox::{msg_path}"
                detail_cache[message_id] = details
                records.append(MessageRecord(message_id, f"{person_dir.name}/inbox", True, details.sent_at, details.sender, details.recipient, _message_preview(details.body), len(details.attachments)))

        done = person_dir / "done"
        if done.exists():
            for zip_path in sorted(done.glob("*.zip"), reverse=True):
                with zipfile.ZipFile(zip_path, "r") as archive:
                    md_files = [name for name in archive.namelist() if name.endswith(".md")]
                    if not md_files:
                        continue
                    details = parse_message_text(archive.read(md_files[0]).decode("utf-8"))
                    message_id = f"done::{zip_path}::{md_files[0]}"
                    detail_cache[message_id] = details
                    records.append(MessageRecord(message_id, f"{person_dir.name}/done", False, details.sent_at, details.sender, details.recipient, _message_preview(details.body), len(details.attachments)))

    records.sort(key=lambda row: row.sent_at, reverse=True)
    return records, detail_cache


def require_login() -> None:
    if st.session_state.get("authenticated"):
        return

    st.markdown("<h2 style='text-align:center'>OpenAck Admin Login</h2>", unsafe_allow_html=True)
    expected_password = os.environ.get("OPENACK_ADMIN_PASS", "password")

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if username == ADMIN_USER and password == expected_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid credentials")

    st.stop()


def inbox_tab(records: list[MessageRecord], detail_cache: dict[str, MessageDetails]) -> None:
    st.subheader("Inbox")
    if not records:
        st.info("No messages found.")
        return

    for row in records:
        label = "🟩" if row.is_new else ""
        cols = st.columns([0.6, 0.9, 2.0, 1.2, 1.2, 2.8, 1.0])
        selected = cols[0].checkbox("", key=f"sel-{row.message_id}")
        cols[1].write(label)
        cols[2].write(_parse_iso_dt(row.sent_at))
        cols[3].write(row.sender)
        cols[4].write(row.recipient)
        cols[5].write(row.preview)
        cols[6].write(str(row.attachments_count))

        ops = st.columns([1, 1, 4])
        if ops[0].button("Reply", key=f"reply-{row.message_id}"):
            st.session_state.compose_to = row.sender
            st.session_state.compose_from = row.recipient
            st.session_state.jump_to_new = True
        if ops[1].button("Open", key=f"open-{row.message_id}"):
            st.session_state.open_message_id = row.message_id

        selected_ids = st.session_state.setdefault("selected_ids", set())
        if selected:
            selected_ids.add(row.message_id)
        else:
            selected_ids.discard(row.message_id)

        st.divider()

    selected_ids = st.session_state.get("selected_ids", set())
    if len(selected_ids) > 1 and st.button("Delete Selected", type="primary"):
        deleted = 0
        for message_id in list(selected_ids):
            if message_id.startswith("inbox::"):
                msg_path = Path(message_id.split("::", 1)[1])
                if msg_path.exists():
                    msg_path.unlink()
                    deleted += 1
        st.session_state["selected_ids"] = set()
        st.success(f"Deleted {deleted} inbox message(s).")
        st.rerun()

    open_id = st.session_state.get("open_message_id")
    if not open_id:
        return

    details = detail_cache.get(open_id)
    if not details:
        st.warning("Message details unavailable.")
        return

    st.markdown("---")
    st.subheader("Message Viewer")
    st.markdown(f"**From:** {details.sender}  ")
    st.markdown(f"**To:** {details.recipient}  ")
    st.markdown(f"**Sent:** {_parse_iso_dt(details.sent_at)}")
    st.markdown(details.body)

    if details.attachments:
        st.markdown("**Attachments**")
        for attachment in details.attachments:
            filename = Path(attachment).name
            if open_id.startswith("done::"):
                _, zip_path_raw, message_member = open_id.split("::", 2)
                with zipfile.ZipFile(zip_path_raw, "r") as archive:
                    resolved_name = resolve_archived_attachment_name(archive.namelist(), attachment, message_member)
                    if not resolved_name:
                        continue
                    data = archive.read(resolved_name)
            else:
                attachment_path = Path(attachment)
                if not attachment_path.exists():
                    continue
                data = attachment_path.read_bytes()

            st.download_button(f"Download {filename}", data=data, file_name=filename, key=f"dl-{open_id}-{filename}")

    if st.button("Reply from viewer", key="reply-viewer"):
        st.session_state.compose_to = details.sender
        st.session_state.compose_from = details.recipient
        st.session_state.jump_to_new = True


def new_message_tab(people: list[str]) -> None:
    st.subheader("New Message")
    if not people:
        st.warning("No people found in directory. Add people in Admin tab first.")
        return

    default_from = st.session_state.get("compose_from", ADMIN_USER)
    default_to = st.session_state.get("compose_to", people[0])

    col1, col2 = st.columns(2)
    sender = col1.selectbox("From", options=people, index=people.index(default_from) if default_from in people else 0)
    recipient = col2.selectbox("To", options=people, index=people.index(default_to) if default_to in people else 0)

    st.caption("Rich markdown editor (supports selection formatting and keyboard shortcuts like Ctrl+B / Ctrl+I).")
    quill_html = st_quill(
        value=st.session_state.get("compose_html", ""),
        html=True,
        placeholder="Write your message...",
        key="compose_editor",
        toolbar=[
            ["bold", "italic", "underline", "strike"],
            [{"header": [1, 2, 3, False]}],
            [{"list": "ordered"}, {"list": "bullet"}, {"list": "check"}],
            ["blockquote", "code-block", "link"],
            ["clean"],
        ],
    )
    st.session_state.compose_html = quill_html or ""
    markdown_message = html_to_markdown(st.session_state.compose_html).strip()

    with st.expander("Markdown preview source", expanded=False):
        st.code(markdown_message or "", language="markdown")

    upload_files = st.file_uploader("Attachments", accept_multiple_files=True, help="Upload files (staged in /tmp before send).")

    if st.button("Send", type="primary"):
        staged_files: list[tuple[str, bytes]] = []
        for upload in upload_files or []:
            data = upload.read()
            (Path(tempfile.gettempdir()) / upload.name).write_bytes(data)
            staged_files.append((upload.name, data))

        try:
            result = handle_send_message(sender, [recipient], markdown_message, staged_files)
        except ValueError as err:
            st.error(str(err))
            return

        st.session_state.compose_html = ""
        st.success(f"Message sent at {result['sent_at']} from {sender} to {recipient}")


def admin_tab(people: list[str], records: list[MessageRecord]) -> None:
    st.subheader("Admin")
    st.caption(f"Messages root (OPENACK_MESSAGES_ROOT): {MESSAGES_ROOT}")
    st.caption(f"People file (OPENACK_PEOPLE_FILE): {PEOPLE_FILE}")

    st.markdown("### People directory")
    new_person = st.text_input("Add person/agent")
    cols = st.columns([1, 1, 3])
    if cols[0].button("Add") and new_person.strip():
        write_people(people + [new_person])
        st.rerun()

    delete_target = cols[1].selectbox("Delete person", options=[""] + people)
    if cols[1].button("Delete") and delete_target:
        write_people([person for person in people if person != delete_target])
        st.rerun()

    st.code(PEOPLE_FILE.read_text(encoding="utf-8") if PEOPLE_FILE.exists() else "people: []", language="yaml")
    st.write(f"Total messages indexed: {len(records)}")

    st.markdown("### Transaction logs")
    if LOG_PATH.exists():
        st.text_area("transactions.log", LOG_PATH.read_text(encoding="utf-8"), height=220)
    else:
        st.info("No transaction logs yet.")


def main() -> None:
    st.set_page_config(page_title="OpenAck Dashboard", layout="wide")
    require_login()

    theme_mode = st.sidebar.selectbox("Theme", ["System", "Light", "Dark"], index=0)
    apply_ui_theme(theme_mode)

    people = ensure_admin_in_people()
    records, detail_cache = scan_messages()

    tabs = st.tabs(["Inbox", "New message", "Admin"])
    with tabs[0]:
        inbox_tab(records, detail_cache)
    with tabs[1]:
        new_message_tab(people)
    with tabs[2]:
        admin_tab(people, records)

    if st.session_state.get("jump_to_new"):
        st.info("Reply pre-filled. Open the New message tab to send.")
        st.session_state.jump_to_new = False


if __name__ == "__main__":
    main()
