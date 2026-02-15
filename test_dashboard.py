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


def test_filter_and_sort_records_filters_by_recipient_and_sorts_sender():
    records = [
        dashboard.MessageRecord("1", "alice/inbox", True, "2026-01-02T00:00:00Z", "zoe", "alice", "z", 0),
        dashboard.MessageRecord("2", "bob/inbox", True, "2026-01-01T00:00:00Z", "amy", "bob", "a", 1),
        dashboard.MessageRecord("3", "bob/inbox", False, "2026-01-03T00:00:00Z", "mike", "bob", "m", 2),
    ]

    filtered = dashboard.filter_and_sort_records(
        records,
        recipient_filter="bob",
        sort_by="sender",
        sort_ascending=True,
    )

    assert [row.message_id for row in filtered] == ["2", "3"]


def test_delete_selected_messages_removes_inbox_and_done_files(tmp_path):
    inbox_file = tmp_path / "alice" / "inbox" / "message.md"
    inbox_file.parent.mkdir(parents=True)
    inbox_file.write_text("hello", encoding="utf-8")

    done_file = tmp_path / "alice" / "done" / "message.zip"
    done_file.parent.mkdir(parents=True)
    done_file.write_bytes(b"zip")

    deleted = dashboard.delete_selected_messages(
        {
            f"inbox::{inbox_file}",
            f"done::{done_file}::message.md",
        }
    )

    assert deleted == 2
    assert not inbox_file.exists()
    assert not done_file.exists()


def test_selected_ids_visible_in_current_view_excludes_hidden_rows():
    visible = [
        dashboard.MessageRecord("1", "alice/inbox", True, "2026-01-01T00:00:00Z", "zoe", "alice", "z", 0),
        dashboard.MessageRecord("2", "bob/inbox", True, "2026-01-02T00:00:00Z", "amy", "bob", "a", 1),
    ]

    visible_selected_ids = dashboard.selected_ids_visible_in_current_view({"2", "3"}, visible)

    assert visible_selected_ids == {"2"}


def test_build_pagination_window_compacts_long_page_ranges():
    pages = dashboard.build_pagination_window(current_page=10, total_pages=20, sibling_count=1)

    assert pages == [1, None, 9, 10, 11, None, 20]


def test_require_login_does_not_allow_query_param_bypass(monkeypatch):
    class StopCalled(Exception):
        pass

    class DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.query_params = {"auth": "1"}

        def markdown(self, *args, **kwargs):
            return None

        def columns(self, _spec):
            return DummyColumn(), DummyColumn(), DummyColumn()

        def form(self, *_args, **_kwargs):
            return DummyColumn()

        def text_input(self, _label, **_kwargs):
            return ""

        def form_submit_button(self, *_args, **_kwargs):
            return False

        def stop(self):
            raise StopCalled

    fake_st = FakeStreamlit()
    monkeypatch.setattr(dashboard, "st", fake_st)

    try:
        dashboard.require_login()
    except StopCalled:
        pass
    else:
        raise AssertionError("require_login should stop when not authenticated")

    assert fake_st.session_state.get("authenticated") is not True
