# FastAPI on uvicorn. ffmpeg transcodes Telegram voice notes and browser clips.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Infisical CLI: start.sh pulls the API's secrets from Infisical at boot.
ARG INFISICAL_VERSION=0.45.5
ARG INFISICAL_SHA256=bdbcd4d990311cf5a0f8b9dac5a65b90d4b2faa9e48f30069590486b11fccb2d
RUN curl -fsSL -o /tmp/infisical.tgz \
        "https://github.com/Infisical/cli/releases/download/v${INFISICAL_VERSION}/cli_${INFISICAL_VERSION}_linux_amd64.tar.gz" \
    && echo "${INFISICAL_SHA256}  /tmp/infisical.tgz" | sha256sum -c - \
    && tar -xzf /tmp/infisical.tgz -C /usr/local/bin infisical \
    && rm /tmp/infisical.tgz

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --create-home stark && chown -R stark /app
USER stark

ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "start.sh"]
