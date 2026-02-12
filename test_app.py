from pathlib import Path

from app import OPENAPI_SPEC, handle_send_message, load_valid_people


def test_load_valid_people_lowercases_names(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- lobsty\n- David\n- Michael\n", encoding="utf-8")
    monkeypatch.setattr("app.PEOPLE_FILE", people_file)

    people = load_valid_people()
    assert people == {"lobsty", "david", "michael"}


def test_send_message_to_multiple_recipients_with_attachments(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- c\n- a\n- b\n", encoding="utf-8")

    monkeypatch.setattr("app.MESSAGES_ROOT", tmp_path / "messages")
    monkeypatch.setattr("app.LOG_PATH", tmp_path / "transactions.log")
    monkeypatch.setattr("app.PEOPLE_FILE", people_file)

    response = handle_send_message(
        "C",
        ["A", "B"],
        "Hello both",
        [("one.txt", b"file one"), ("two.png", b"file two")],
    )

    assert response["from"] == "c"
    assert response["to"] == ["a", "b"]
    assert len(response["deliveries"]) == 2

    for delivery in response["deliveries"]:
        message_file = Path(delivery["message_file"])
        assert message_file.exists()
        assert message_file.parent.name == "inbox"
        assert message_file.name.endswith(".md")

        text = message_file.read_text(encoding="utf-8")
        assert "from: c" in text
        assert f"to: {delivery['recipient']}" in text
        assert "=== FOOTER ===" in text
        assert "attachments:" in text
        for attachment_path in delivery["attachments"]:
            attachment = Path(attachment_path)
            assert attachment.exists()
            assert attachment.parent == message_file.parent
            assert "-attachment" in attachment.name

    log_content = (tmp_path / "transactions.log").read_text(encoding="utf-8")
    assert "from=c,to=a" in log_content
    assert "from=c,to=b" in log_content


def test_send_message_without_attachments_has_reply_url(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- a\n- b\n", encoding="utf-8")

    monkeypatch.setattr("app.MESSAGES_ROOT", tmp_path / "messages")
    monkeypatch.setattr("app.LOG_PATH", tmp_path / "transactions.log")
    monkeypatch.setattr("app.PEOPLE_FILE", people_file)

    response = handle_send_message("A", ["B"], "Reply please", [])

    delivery = response["deliveries"][0]
    message_text = Path(delivery["message_file"]).read_text(encoding="utf-8")
    assert "reply_url: /messages?from=b&to=a" in message_text


def test_reject_unknown_recipient(tmp_path, monkeypatch):
    people_file = tmp_path / "people.yml"
    people_file.write_text("people:\n- a\n", encoding="utf-8")
    monkeypatch.setattr("app.PEOPLE_FILE", people_file)

    try:
        handle_send_message("A", ["B"], "hello", [])
        assert False, "Expected ValueError"
    except ValueError as err:
        assert "Recipient(s) not in directory: b" in str(err)


def test_howto_is_openapi_spec():
    assert OPENAPI_SPEC["openapi"].startswith("3.")
    assert "/messages" in OPENAPI_SPEC["paths"]
    assert "/howto" in OPENAPI_SPEC["paths"]
    assert "/directory" in OPENAPI_SPEC["paths"]
    assert OPENAPI_SPEC["paths"]["/messages"]["post"]["requestBody"]["required"] is True
