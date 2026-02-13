# OpenAck middleware

OpenAck is a lightweight middleware that lets multiple agents exchange messages through a shared filesystem in a predictable format.

## Why this middleware for agents?

- Gives agents a common delivery layer (`POST /messages`) instead of direct agent-to-agent coupling.
- Persists every delivery to disk so agents can read asynchronously.
- Supports fan-out (`to=A,to=B`) with one API call.
- Keeps transaction logging minimal (`from`, `to`, `datetime`).
- Lets humans centrally control valid participants via `people.yml`.

## Human setup with Docker Compose

Prepare local folders/files:

```bash
mkdir -p openack/messages/agent-a/inbox openack/messages/agent-a/done
mkdir -p openack/messages/agent-b/inbox openack/messages/agent-b/done
mkdir -p openack/config
cat > openack/config/people.yml <<'YAML'
people:
- agent-a
- agent-b
YAML
```

Example compose update:

```yaml
services:
  openack:
    image: michaelpc/openack:latest
    volumes:
      - ./openack/messages:/messages
      - ./openack/config:/var/lib/openack

  example-agent-A:
    image: openclaw
    environment:
      OPENACK_API: http://openack:8080
    volumes:
      - ./openack/messages/agent-a:/messages/agent-a

  example-agent-B:
    image: openclaw
    environment:
      OPENACK_API: http://openack:8080
    volumes:
      - ./openack/messages/agent-b:/messages/agent-b
```

## Message file layout

For `A -> B`, OpenAck writes:

- Message file: `/messages/b/inbox/YYYY-MM-DDTHH:MM:SSZ-<uuid>.md`
- Attachments: `/messages/b/inbox/<uuid>-attachment1.ext`, `<uuid>-attachment2.ext`, ...

Message file format:

- Header: `from`, `to`, `sent_at`
- Body: message content
- Footer: attachment paths, or reply URL when no attachment

After agent B processes a message, B should archive message + attachments into `done` (for example `/messages/b/done/YYYY-MM-DDTHH:MM:SSZ-<uuid>.zip`).

## API endpoints

- `POST /messages`
- `GET /directory`
- `GET /howto` (OpenAPI JSON)
- `GET /docs` (Swagger UI)

## Directory source

OpenAck reads valid people from:

- `/var/lib/openack/people.yml`

Names are normalized to lowercase for validation and folder naming.

## Streamlit human dashboard

A built-in Streamlit UI is available for human monitoring and messaging.

- App file: `dashboard.py`
- Port: `8081`
- Login: username `admin`, password from environment variable `OPENACK_ADMIN_PASS`
- Reads messages from `OPENACK_MESSAGES_ROOT` (default `/messages`)
- Reads participants from `OPENACK_PEOPLE_FILE` (default `/var/lib/openack/people.yml`)

Run it with:

```bash
export OPENACK_ADMIN_PASS=change-me
streamlit run dashboard.py --server.port 8081 --server.address 0.0.0.0
```

Dashboard tabs:

- **Inbox**: unified list of new (green flag) and read/archived messages with quick actions and message viewer.
- **New message**: compose markdown messages, choose sender/recipient, use extended markdown formatting shortcuts, upload attachments (staged in `/tmp` before send).
- **Admin**: review logs/message counts and add/remove people from `people.yml`.

- Theme selector (System/Light/Dark) is available in the sidebar.
- Streamlit toolbar/deploy button is hidden in the dashboard UI.
