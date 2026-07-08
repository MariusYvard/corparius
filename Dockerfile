FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY companies ./companies

ENV CORP_DATA_PATH=/app/data
VOLUME ["/app/data", "/app/companies"]

# Run the example company on a loop by default. Override the command to point at
# your own config, or exec `python -m app.cli ...` for one-off actions.
CMD ["python", "-m", "app.cli", "run", "--company", "example", "--loop"]
