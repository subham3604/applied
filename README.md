<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/LangGraph-Agentic_DAG-FF6F00?style=for-the-badge&logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/PostgreSQL-16_+_pgvector-336791?style=for-the-badge&logo=postgresql&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
</p>

# Applied — Autonomous Career Pipeline Engine

Applied is an event-driven, agentic career intelligence platform that automates job tracking and resume tailoring for high-volume job seekers. By combining headless **Gmail ATS triage**, deterministic **LangGraph state progression DAGs**, and grounded **`pgvector` RAG resume tailoring**, Applied eliminates manual bookkeeping and ensures candidates never lose track of application stages or tailored resume versions.

The backend is built with **FastAPI** and **LangGraph**, deployed on **Render** with a **Supabase PostgreSQL 16 (`pgvector`)** database. The frontend is a modern **React 19** Kanban dashboard hosted on **Vercel**.

### Why Applied?
Job applicants applying across multiple portals (Workday, Greenhouse, Lever, Taleo) face constant organizational chaos: emails arrive wrapped in automated corporate disclaimers, tailored resume versions drift without records, and silent portals drop status updates. Applied solves this by turning AI into an **autonomous state controller**—parsing incoming correspondence, advancing deterministic state machines, and grounding resume tailoring in verified vector embeddings.

| | Link |
|---|---|
| 🌐 **Live Web Application** | [applied-xi.vercel.app](https://applied-xi.vercel.app) |
| 📖 **API Docs (Swagger UI)** | [applied-api.onrender.com/docs](https://applied-api.onrender.com/docs) |
| 🏛️ **System Architecture** | [docs/architecture.md](docs/architecture.md) |
| 📊 **Model Evaluation & Benchmark** | [docs/evaluation.md](docs/evaluation.md) |
| 🔌 **API Reference** | [docs/api.md](docs/api.md) |
| 💻 **Local Setup Guide** | [docs/local-development.md](docs/local-development.md) |

---

## System Architecture

```mermaid
graph TD
    Client["Candidate Browser (React 19 + TanStack)"]
    Caddy["Caddy 2 Reverse Proxy (TLS / Ingress)"]
    FastAPI["FastAPI Backend Server (Render)"]
    Worker["Autonomous Triage Worker (APScheduler)"]
    Gmail["Google Gmail API (OAuth2)"]
    DB[("Supabase PostgreSQL 16 + pgvector")]
    OpenAI["OpenAI API (gpt-4o-mini + text-embedding-3-small)"]

    Client -->|HTTPS REST| Caddy
    Caddy -->|Proxy :8000| FastAPI
    
    Gmail -->|Periodic Polling (15m)| Worker
    Worker -->|1. Regex Pre-Filter| Worker
    Worker -->|2. LangGraph 4-Node DAG| OpenAI
    Worker -->|3. Persist State Changes| DB

    FastAPI -->|Extract JD & Score Requirements| OpenAI
    FastAPI -->|Cosine Similarity Search (1536-d)| DB
    FastAPI -->|Audit Events & Application CRUD| DB
    FastAPI <-->|Live Updates| Client
```

> For deep architectural specifications, component trade-offs, and state invariants, see [docs/architecture.md](docs/architecture.md).

---

## Features

- **Autonomous ATS Ingestion** — Headless Gmail background worker with 5-tier entity resolution for Workday, Greenhouse, Lever, and Ashby.
- **Deterministic State Machine** — LangGraph DAG enforcing strict, non-reversible lifecycle progression (`APPLIED` $\rightarrow$ `OA_PENDING` $\rightarrow$ `INTERVIEW_ROUND` $\rightarrow$ `OFFER` / `REJECTED`).
- **Grounded RAG Resume Tailor** — 1536-dimensional cosine vector retrieval (`pgvector`) matching job requirements against the Master Experience Vault.
- **Anti-Hallucination Guard** — Automated verification layer ensuring generated resumes contain zero ungrounded technical claims.
- **Empirically Evaluated** — Hardened against 73 real-world samples with a 93.75% defense rate against deceptive adversarial traps.
- **Interactive Kanban Surface** — React 19 + TanStack Start UI featuring real-time stage updates, detail drawers, and 1-click human overrides.
- **Master Experience Vault** — Full web-based CRUD dashboard for career achievements with automatic vector re-indexing.

---

## How It Works — End to End

### 1. User Drops a Job Description
The user pastes a raw Job Description (JD) at `/new-drop`. The backend extracts core competencies, queries the Master Experience Vault using cosine similarity, validates the selections, and creates an application in the `APPLIED` state.

### 2. Tailored Resume Snapshotting
The matched bullet points are compiled into an immutable resume snapshot linked to the application ID, guaranteeing a permanent record of the exact claims submitted to that employer.

### 3. Inbound Recruiter Email Triage
Every 15 minutes, the background worker polls the Gmail API for new messages. Messages pass a Tier-1 regex heuristic pre-filter, dropping promotional noise in under 5ms.

### 4. Classification & State Progression
Relevant emails are parsed through a 4-node LangGraph state machine. When an online assessment or interview invitation is detected, the application automatically advances and logs an immutable audit event.

### 5. Human-in-the-Loop Overrides
Ambiguous correspondence or edge cases trigger an *Attention Required* banner in the UI, allowing the user to reassign or update application state with a single click.

---

## Empirical Evaluation & Benchmarks

The extraction and classification engine was evaluated against a **73-sample real-world dataset** annotated with ground-truth labels, including **16 high-capacity adversarial traps** (polite rejections, course promotions, referral confusion, unsubmitted drafts):

| Metric | Target Threshold | Achieved Benchmark | Status |
|---|:---:|:---:|:---:|
| **Stage Classification Accuracy** | $\ge 90.0\%$ | **`92.59%`** | Exceeded (+11.1%) |
| **Company Extraction Precision** | $\ge 93.0\%$ | **`100.00%`** | Exceeded (+16.7%) |
| **Relevance Gate Precision** | $\ge 95.0\%$ | **`98.15%`** | Exceeded (+19.2%) |
| **Relevance Gate Recall** | $\ge 95.0\%$ | **`98.15%`** (53/54) | Exceeded (+3.7%) |
| **Adversarial Trap Defense** | $\ge 85.0\%$ | **`93.75%`** (15/16) | Exceeded (+43.8%) |

> For full confusion matrices, category breakdowns, and ablation notes, see [docs/evaluation.md](docs/evaluation.md).

---

## Tech Stack

| Category | Technologies |
|---|---|
| **Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 |
| **AI & Agents** | LangGraph, LangChain, Instructor, OpenAI (`gpt-4o-mini`, `text-embedding-3-small`) |
| **Database & Vectors** | PostgreSQL 16, `pgvector`, SQLAlchemy, Alembic |
| **Frontend** | React 19, TanStack Start, TypeScript, Tailwind CSS |
| **Worker & Automation** | APScheduler, Google Gmail API, OAuth2 |
| **Infrastructure & DevOps**| Docker, Docker Compose, Caddy 2, Render, Vercel |
| **Testing** | pytest, pytest-asyncio, HTTPX (141 automated tests) |

---

## API Overview

Interactive Swagger UI: **[applied-api.onrender.com/docs](https://applied-api.onrender.com/docs)**

| Endpoint | Method | Description |
|---|---|---|
| `/api/pipeline/single-drop` | `POST` | Ingests raw JD, matches vector bullets, and creates application |
| `/api/applications` | `GET` | Lists all active applications with current stages and timelines |
| `/api/applications/{id}/status` | `PATCH` | Manual status override for drag-and-drop Kanban updates |
| `/api/vault` | `GET`, `POST` | View and insert verified career bullets with automated embeddings |
| `/health` | `GET` | Health check endpoint for container probes |

> Full endpoint documentation and request/response payloads: [docs/api.md](docs/api.md)

---

## Getting Started

```bash
git clone https://github.com/subham3604/applied.git
cd applied
cp .env.example .env
docker compose up -d --build
```

> [!IMPORTANT]
> **Full local setup guide** (prerequisites, virtual environment, database migrations, vault seeding): [docs/local-development.md](docs/local-development.md)  
> **Empirical evaluation benchmark & adversarial analysis**: [docs/evaluation.md](docs/evaluation.md)

---

## License

Distributed under the MIT License. Developed for portfolio and educational purposes.
