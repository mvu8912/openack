from fetch import OPENAPI_SPEC, fetch_messages_by_id


def test_fetch_messages_by_id_returns_payload_and_archives(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- paul\n- david\n", encoding="utf-8")

    ids_file = tmp_path / "agent_ids.yml"
    ids_file.write_text("id:\n  Uweeuhdh123: paul\n", encoding="utf-8")

    inbox = tmp_path / "messages" / "paul" / "inbox"
    inbox.mkdir(parents=True)
    msg = inbox / "2026-02-13T02:15:26Z-aaaa.md"
    attachment = inbox / "aaaa-attachment1.txt"
    attachment.write_text("file body", encoding="utf-8")
    msg.write_text(
        "\n".join(
            [
                "=== HEADER ===",
                "from: david",
                "to: paul",
                "sent_at: 2026-02-13T02:15:26+00:00",
                "",
                "hello",
                "=== FOOTER ===",
                "attachments:",
                f"- {attachment}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("fetch.PEOPLE_FILE", people_file)
    monkeypatch.setattr("fetch.AGENT_IDS_FILE", ids_file)
    monkeypatch.setattr("fetch.MESSAGES_ROOT", tmp_path / "messages")

    messages = fetch_messages_by_id("Uweeuhdh123")

    assert len(messages) == 1
    assert messages[0]["from"] == "david"
    assert messages[0]["to"] == "paul"
    assert messages[0]["message"] == "hello"
    assert messages[0]["attachments"][0]["file"] == "aaaa-attachment1.txt"
    assert "content" in messages[0]["attachments"][0]

    assert not msg.exists()
    assert not attachment.exists()

    done = tmp_path / "messages" / "paul" / "done"
    archives = list(done.glob("*.zip"))
    assert len(archives) == 1


def test_fetch_messages_by_id_empty_inbox(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- paul\n", encoding="utf-8")

    ids_file = tmp_path / "agent_ids.yml"
    ids_file.write_text("id:\n  Uweeuhdh123: paul\n", encoding="utf-8")

    monkeypatch.setattr("fetch.PEOPLE_FILE", people_file)
    monkeypatch.setattr("fetch.AGENT_IDS_FILE", ids_file)
    monkeypatch.setattr("fetch.MESSAGES_ROOT", tmp_path / "messages")

    assert fetch_messages_by_id("Uweeuhdh123") == []


def test_fetch_openapi_exposes_messages_get():
    assert OPENAPI_SPEC["openapi"].startswith("3.")
    assert "/messages" in OPENAPI_SPEC["paths"]
    assert "get" in OPENAPI_SPEC["paths"]["/messages"]


def test_fetch_uses_last_footer_marker_and_ignores_body_lookalikes(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- paul\n- david\n", encoding="utf-8")

    ids_file = tmp_path / "agent_ids.yml"
    ids_file.write_text("id:\n  Uweeuhdh123: paul\n", encoding="utf-8")

    inbox = tmp_path / "messages" / "paul" / "inbox"
    inbox.mkdir(parents=True)

    # Path outside the inbox should never be treated as an attachment.
    external_file = tmp_path / "secret.txt"
    external_file.write_text("do-not-read-or-delete", encoding="utf-8")

    msg = inbox / "2026-02-13T02:15:26Z-aaaa.md"
    msg.write_text(
        "\n".join(
            [
                "=== HEADER ===",
                "from: david",
                "to: paul",
                "sent_at: 2026-02-13T02:15:26+00:00",
                "",
                "first body line",
                "=== FOOTER ===",
                f"- {external_file}",
                "last body line",
                "=== FOOTER ===",
                "attachments:",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("fetch.PEOPLE_FILE", people_file)
    monkeypatch.setattr("fetch.AGENT_IDS_FILE", ids_file)
    monkeypatch.setattr("fetch.MESSAGES_ROOT", tmp_path / "messages")

    messages = fetch_messages_by_id("Uweeuhdh123")

    assert len(messages) == 1
    assert messages[0]["attachments"] == []
    assert "=== FOOTER ===\n- " in messages[0]["message"]
    assert external_file.exists()
