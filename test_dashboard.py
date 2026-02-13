import zipfile

import dashboard


def test_parse_message_text_extracts_header_body_and_attachments():
    text = """=== HEADER ===
from: alice
to: bob
sent_at: 2026-01-01T12:00:00Z

Hello **Bob**!
=== FOOTER ===
attachments:
- /messages/bob/inbox/abc-attachment1.txt
"""

    details = dashboard.parse_message_text(text)

    assert details.sender == "alice"
    assert details.recipient == "bob"
    assert details.sent_at == "2026-01-01T12:00:00Z"
    assert details.body == "Hello **Bob**!"
    assert details.attachments == ["/messages/bob/inbox/abc-attachment1.txt"]


def test_scan_messages_reads_inbox_and_done_zip(tmp_path, monkeypatch):
    messages_root = tmp_path / "messages"
    inbox = messages_root / "bob" / "inbox"
    done = messages_root / "bob" / "done"
    inbox.mkdir(parents=True)
    done.mkdir(parents=True)

    (inbox / "2026-01-01T00:00:00Z-1.md").write_text(
        """=== HEADER ===
from: alice
to: bob
sent_at: 2026-01-01T00:00:00Z

inbox body
=== FOOTER ===
reply_url: /messages?from=bob&to=alice
""",
        encoding="utf-8",
    )

    done_zip = done / "2026-01-02T00:00:00Z-1.zip"
    with zipfile.ZipFile(done_zip, "w") as archive:
        archive.writestr(
            "2026-01-02T00:00:00Z-1.md",
            """=== HEADER ===
from: carol
to: bob
sent_at: 2026-01-02T00:00:00Z

processed body
=== FOOTER ===
reply_url: /messages?from=bob&to=carol
""",
        )

    monkeypatch.setattr(dashboard, "MESSAGES_ROOT", messages_root)

    records, details = dashboard.scan_messages()

    assert len(records) == 2
    assert records[0].sender == "carol"
    assert records[0].is_new is False
    assert records[1].sender == "alice"
    assert records[1].is_new is True
    assert len(details) == 2


def test_write_people_normalizes_entries(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    monkeypatch.setattr(dashboard, "PEOPLE_FILE", people_file)

    dashboard.write_people(["Alice", "bob", "alice", " "])

    text = people_file.read_text(encoding="utf-8")
    assert "- alice" in text
    assert "- bob" in text


def test_resolve_archived_attachment_name_handles_absolute_footer_paths():
    archive_names = [
        "2026-01-02T00:00:00Z-1.md",
        "abc-attachment1.txt",
    ]

    resolved = dashboard.resolve_archived_attachment_name(
        archive_names,
        "/messages/bob/inbox/abc-attachment1.txt",
        "2026-01-02T00:00:00Z-1.md",
    )

    assert resolved == "abc-attachment1.txt"


def test_resolve_archived_attachment_name_prefers_message_directory_member():
    archive_names = [
        "archive/2026-01-02T00:00:00Z-1.md",
        "archive/abc-attachment1.txt",
    ]

    resolved = dashboard.resolve_archived_attachment_name(
        archive_names,
        "/messages/bob/inbox/abc-attachment1.txt",
        "archive/2026-01-02T00:00:00Z-1.md",
    )

    assert resolved == "archive/abc-attachment1.txt"


def test_ensure_admin_in_people(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- bob\n", encoding="utf-8")
    monkeypatch.setattr(dashboard, "PEOPLE_FILE", people_file)

    people = dashboard.ensure_admin_in_people()

    assert "admin" in people
    assert "- admin" in people_file.read_text(encoding="utf-8")
