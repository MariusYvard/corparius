# Base image pinned by digest for reproducible builds. To update: run
#   docker buildx imagetools inspect python:3.12-slim
# and replace the digest below (keep the tag for readability).
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

WORKDIR /app

# Install from the pinned, hash-checked lock so the image is reproducible and
# every dependency is verified against a known SHA-256.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
COPY companies ./companies

ENV CORP_DATA_PATH=/app/data
VOLUME ["/app/data", "/app/companies"]

EXPOSE 8600

# Serve the operator console by default; docker-compose.yml overrides per service.
CMD ["python", "-m", "app.cli", "ui", "--host", "0.0.0.0", "--port", "8600"]
