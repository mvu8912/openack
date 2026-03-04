FROM --platform=$BUILDPLATFORM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends perl cpanminus build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY cpanfile /app/cpanfile
RUN cpanm --notest --installdeps .

COPY app.py /app/app.py
COPY fetch.py /app/fetch.py
COPY app.psgi /app/app.psgi
COPY lib /app/lib
COPY views /app/views
COPY public /app/public

ENV OPENACK_MESSAGES_ROOT=/messages \
    OPENACK_PEOPLE_FILE=/var/lib/openack/people.yml \
    OPENACK_PORT=8080 \
    OPENACK_ADMIN_PORT=8081 \
    PYTHONUNBUFFERED=1

EXPOSE 8080 8081

CMD ["plackup", "-I", "lib", "-E", "deployment", "-s", "Starman", "--host", "0.0.0.0", "--port", "8081", "app.psgi"]
