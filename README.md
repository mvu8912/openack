# OpenAck middleware

OpenAck is a lightweight middleware that lets multiple agents exchange messages through a shared filesystem in a predictable format. The send API runs in `app.py`, and a dedicated fetch API runs in `fetch.py` so agents receive messages by ID without reading inbox files directly.

## Why this middleware for agents?

- Gives agents a common delivery layer (`POST /messages`) instead of direct agent-to-agent coupling.
- Persists every delivery to disk so agents can read asynchronously.
- Supports fan-out (`to=A,to=B`) with one API call.
- Keeps transaction logging minimal (`from`, `to`, `datetime`).
- Lets humans centrally control valid participants via `people.yml`.

## Human setup with Docker Compose

Prepare local folders/files:

```bash
mkdir -p openack/messages/paul/inbox openack/messages/paul/done
mkdir -p openack/messages/david/inbox openack/messages/david/done
mkdir -p openack/config
cat > openack/config/people.yml <<'YAML'
people:
- paul
- david
YAML
cat > openack/config/agent_ids.yml <<'YAML'
id:
  Uweeuhdh123: paul
  Hsududh889: david
YAML
```

If you want to mirror the default service naming from this repository, use `openack` and `openack-admin` and expose the dashboard on host port `18081`:

```yaml
services:
  openack:
    image: michaelpc/openack:latest
    volumes:
      - ./openack/messages:/messages
      - ./openack/config:/var/lib/openack

  openack-admin:
    extends: openack
    ports:
      - 18081:8081
    command:
      - plackup
      - -I
      - lib
      - -E
      - deployment
      - -s
      - Starman
      - --host
      - 0.0.0.0
      - --port
      - "8081"
      - app.psgi
```

Example compose update:

```yaml
services:
  openack:
    image: michaelpc/openack:latest
    volumes:
      - ./openack/messages:/messages
      - ./openack/config:/var/lib/openack

  openack-fetch:
    extends: openack
    command: ["python", "fetch.py"]
    environment:
      OPENACK_PORT: 9090
      OPENACK_AGENT_IDS_FILE: /var/lib/openack/agent_ids.yml

  paul: # paul
    image: openclaw
    environment:
      OPENACK_API: http://openack:8080
      OPENACK_FETCH_API: http://openack-fetch:9090
      OPENACK_AGENT_ID: Uweeuhdh123

  david: # david
    image: openclaw
    environment:
      OPENACK_API: http://openack:8080
      OPENACK_FETCH_API: http://openack-fetch:9090
      OPENACK_AGENT_ID: Hsududh889
```

Then open the dashboard at `http://localhost:18081`.

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

- Send API (`app.py`): `POST /messages`, `GET /directory`, `GET /howto`, `GET /docs`
- Fetch API (`fetch.py`): `GET /messages?id=<agent-id>`, `GET /howto`, `GET /docs`

## Directory source

OpenAck reads valid people from:

- `/var/lib/openack/people.yml`

Names are normalized to lowercase for validation and folder naming.

## Perl Dancer2 human dashboard

A built-in Perl dashboard is available for human monitoring and messaging.

- Backend: Dancer2 + Template Toolkit
- Frontend: HTML + CSS + JavaScript
- App entrypoint: `app.psgi` (`OpenAck::Admin` in `lib/OpenAck/Admin.pm`)
- Port: `8081`
- Login: username `admin`, password from `OPENACK_ADMIN_PASS` (defaults to `password` when unset)
- Reads participants from `OPENACK_PEOPLE_FILE` (default `/var/lib/openack/people.yml`)

Run it with:

```bash
export OPENACK_ADMIN_PASS=change-me
plackup -I lib -E deployment -s Starman --host 0.0.0.0 --port 8081 app.psgi
```

Dashboard sections:

- **New message**: compose and send messages through `POST /messages` with optional attachments.
- **Inbox & Archive**: view inbox messages and archived records, mark inbox items as read (zip archive), and delete records.
- **People directory**: add/remove users from `people.yml`.
