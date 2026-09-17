FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY worker/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy database layer and worker service modules
COPY db/ /app/db/
COPY worker/ /app/worker/

ENV PYTHONPATH=/app

CMD ["python", "-u", "-m", "worker.worker"]
