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
