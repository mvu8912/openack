FROM --platform=$BUILDPLATFORM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY dashboard.py /app/dashboard.py
COPY fetch.py /app/fetch.py

ENV OPENACK_MESSAGES_ROOT=/messages \
    OPENACK_PEOPLE_FILE=/var/lib/openack/people.yml \
    OPENACK_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "app.py"]
