# Base image pinned by digest for reproducible builds. To update: run
#   docker buildx imagetools inspect python:3.12-slim
# and replace the digest below (keep the tag for readability).
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

WORKDIR /app

# Install from the pinned, hash-checked lock so the image is reproducible and
# every dependency is verified against a known SHA-256.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY corparius ./corparius
COPY companies ./companies
COPY plugins ./plugins

ENV CORP_DATA_PATH=/app/data
VOLUME ["/app/data", "/app/companies"]

EXPOSE 8600

# Run as a non-root user. The store chmods its directory to 0700 and the file to
# 0600, so both must be owned by the uid that will be writing them.
RUN useradd --system --uid 10001 --create-home corparius \
    && mkdir -p /app/data \
    && chown -R corparius:corparius /app
USER corparius

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8600/api/session', timeout=4)" \
    || exit 1

# 0.0.0.0 is correct inside a container - binding loopback would make published
# ports unreachable - but it means the console answers anyone who can route to
# it. docker-compose.yml publishes to 127.0.0.1 only. If you expose this port
# yourself, set CORP_UI_TOKEN, and CORP_UI_ALLOWED_HOSTS to the name you serve
# it under. `python -m corparius.cli doctor` fails the exposure check if you do not.
CMD ["python", "-m", "corparius.cli", "ui", "--host", "0.0.0.0", "--port", "8600"]
