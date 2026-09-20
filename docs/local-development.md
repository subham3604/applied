# Local Development & Setup Guide

This guide walks through configuring, running, and testing the Applied platform in your local environment.

---

## 1. Prerequisites

Ensure you have the following installed locally:
* **Python 3.11+**
* **Node.js 20+** & npm
* **Docker & Docker Compose**
* **OpenAI API Key** (`OPENAI_API_KEY`)
* *(Optional)* Google OAuth2 Client Credentials (for local Gmail API polling)

---

## 2. Environment Configuration

Copy the example environment file and populate your credentials:

```bash
cp .env.example .env
```

### Essential Environment Variables
| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://tracker_admin:tracker_secret_password@localhost:5433/job_tracker` |
| `OPENAI_API_KEY` | OpenAI API key for embeddings and extraction | `sk-...` |
| `OPENAI_MODEL` | Active LLM for LangGraph extraction | `gpt-4o-mini` |
| `EMBEDDING_MODEL` | Vector embedding model | `text-embedding-3-small` |
| `GOOGLE_CLIENT_ID` | OAuth2 Client ID for Gmail API | `...apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | OAuth2 Client Secret for Gmail API | `...` |

---

## 3. Launching Locally

### Option A: Complete Docker Compose Stack (*Recommended*)

Runs the local container stack (FastAPI Backend, Background Worker, and PostgreSQL `pgvector`) with one command:

```bash
# Build and launch all services
docker compose up -d --build

# View container logs
docker compose logs -f
```

* **FastAPI Docs:** `http://localhost:8000/docs`
* **PostgreSQL:** `localhost:5433`

---

### Option B: Native Development (Backend + Frontend)

#### Step 1: Start PostgreSQL with `pgvector`
```bash
docker run -d --name applied-db -p 5433:5432 \
  -e POSTGRES_USER=tracker_admin \
  -e POSTGRES_PASSWORD=tracker_secret_password \
  -e POSTGRES_DB=job_tracker \
  pgvector/pgvector:pg16
```

#### Step 2: Initialize Database & Seed Master Vault
```bash
# Setup Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r web/requirements.txt -r worker/requirements.txt

# Run migrations
alembic upgrade head

# Seed initial experience vault and generate 1536-d embeddings
python scripts/seed_vault.py --file data/master_vault.json
```

#### Step 3: Launch FastAPI Backend
```bash
uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

*(Optional)* To populate the attention banner with realistic ambiguous email items for UI verification:
```bash
curl -X POST http://localhost:8000/api/attention/seed-demo
```

#### Step 4: Launch React Frontend (Separate Terminal)
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173` to view the interactive Kanban board and attention triage deck.

---

## 4. Running the Test Suite

```bash
# Run all unit and integration tests (143 tests)
pytest tests/ -v

# Run the 73-sample empirical evaluation benchmark
pytest tests/test_extraction_pipeline.py -s -v
```
