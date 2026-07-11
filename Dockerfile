FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY companies ./companies

ENV CORP_DATA_PATH=/app/data
VOLUME ["/app/data", "/app/companies"]

EXPOSE 8600

# Serve the operator console by default; docker-compose.yml overrides per service.
CMD ["python", "-m", "app.cli", "ui", "--host", "0.0.0.0", "--port", "8600"]
