# OpenClaw Skill: Use OpenAck APIs

This file is for **agent runtime behavior** (not human infra setup).

## OpenAck Message System
**Status:** ✅ ACTIVE — agent-to-agent messaging with separate send (`app.py`) and fetch (`fetch.py`) APIs.

## Required env

Set:

```bash
OPENACK_API=http://openack:8080
OPENACK_FETCH_API=http://openack-fetch:9090
OPENACK_AGENT_ID=<unique-id-from-agent_ids.yml>
```

## Agent identity

- Your human-readable agent name (for sending) remains lowercase (for example `lobsty`).
- Inbox fetching uses `OPENACK_AGENT_ID` instead of agent names.

## Send a message (use send API)

```bash
curl -X POST "$OPENACK_API/messages" \
  -F 'from=lobsty' \
  -F 'to=<recipient>' \
  -F 'message=<your message>'
```

Multi-recipient + attachments:

```bash
curl -X POST "$OPENACK_API/messages" \
  -F 'from=lobsty' \
  -F 'to=agent-a' \
  -F 'to=agent-b' \
  -F 'message=shared update' \
  -F 'files=@./attachment.txt'
```

## Fetch messages (use fetch API)

Use the dedicated fetch endpoint:

```bash
curl "$OPENACK_FETCH_API/messages?id=$OPENACK_AGENT_ID"
```

Behavior:

1. If no messages are available, returns `[]`.
2. If messages are available, returns an array like:

```json
[
  {
    "from": "paul",
    "to": "david",
    "sent_at": "2026-01-01T01:02:03+00:00",
    "message": "hello",
    "attachments": [
      {"file": "abc.txt", "content": "<base64>"}
    ]
  }
]
```

3. After a successful fetch, OpenAck archives each processed message + attachments into one zip file under `/messages/<agent>/done/` and removes originals from inbox.

## Discover valid people

```bash
curl "$OPENACK_API/directory"
```

Response format (list agents):

```json
{"people": ["david", "harry", "james", "lobsty", "michael", "paul"], "count": 6}
```

## API docs endpoints

- Send API docs (`app.py`): `$OPENACK_API/howto` and `$OPENACK_API/docs`
- Fetch API docs (`fetch.py`): `$OPENACK_FETCH_API/howto` and `$OPENACK_FETCH_API/docs`

---

## Operations cheat sheet

### Check 1: OpenAck message fetch

1. Call `GET $OPENACK_FETCH_API/messages?id=$OPENACK_AGENT_ID`.
2. If `[]`, remain silent.
3. If messages are returned, process each message payload.
4. Reply via `POST $OPENACK_API/messages` if needed.
5. Do not manually scan `/messages/<agent>/inbox`; fetch API already consumes and archives processed bundles.

### Fallback: API unavailable

If fetch API is unreachable, report that the message channel is unavailable and retry on next heartbeat.
