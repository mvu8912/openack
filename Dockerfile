FROM python:3.12-slim

WORKDIR /app

COPY app.py /app/app.py

ENV OPENACK_MESSAGES_ROOT=/messages \
    OPENACK_PEOPLE_FILE=/var/lib/openack/people.yml \
    OPENACK_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "app.py"]
