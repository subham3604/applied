# API Architecture & Endpoint Reference

> **Swagger Source of Truth:** Interactive OpenAPI 3.0 documentation is available live at **[applied-api.onrender.com/docs](https://applied-api.onrender.com/docs)**.

---

## 1. API Overview

The Applied backend exposes a high-concurrency async REST API built with **FastAPI** and **Pydantic v2**, structured across three primary operational domains:

1. **Pipeline & Job Drops:** Ingesting job descriptions, extracting requirements, and triggering vector retrieval.
2. **Applications & Kanban:** Managing application lifecycle states, timeline events, and manual drag-and-drop overrides.
3. **Master Experience Vault:** Curating verified career achievements, technical claims, and 1536-dimensional embeddings.

---

## 2. Core Endpoints

### 2.1 Job Description Ingestion & Tailoring (`/api/applications/parse`)

#### `POST /api/applications/parse`
Parses raw job description text via LLM extraction, performs semantic vector retrieval against the Master Experience Vault (`pgvector`), generates a grounded tailored resume snapshot, and creates an application record.

**Request Payload:**
```json
{
  "jd_text": "We are seeking a backend engineer experienced in distributed systems, Python/FastAPI, and PostgreSQL...",
  "source_platform": "LinkedIn"
}
```

**Response Payload (200 OK):**
```json
{
  "success": true,
  "application_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "company": "Stripe",
  "role": "Backend Software Engineer",
  "stack": ["Python", "FastAPI", "PostgreSQL"],
  "location": "Remote",
  "current_stage": "APPLIED",
  "tailored_bullets": [
    "Architected an event-driven Redis caching layer cutting API latency by 65%."
  ]
}
```

---

### 2.2 Applications & State Management (`/api/applications`)

#### `GET /api/applications`
Retrieves all pipeline applications with current stages, companies, and date timestamps for Kanban board rendering.

#### `PATCH /api/applications/{id}/status`
Allows manual drag-and-drop status overrides from the Kanban board. Bypasses the autonomous worker while logging a manual audit event.

**Request Payload:**
```json
{
  "target_stage": "INTERVIEW_ROUND",
  "notes": "Recruiter scheduled technical round over phone"
}
```

#### `GET /api/applications/{id}/timeline`
Returns the chronological audit trail of all automated and manual state transitions for a specific application.

---

### 2.3 Master Experience Vault (`/api/vault`)

#### `GET /api/vault`
Fetches all verified career achievements stored in the vault, supporting optional category filtering (`category=backend|frontend|data`).

#### `POST /api/vault`
Adds a new technical bullet to the vault. Automatically generates a 1536-dimensional vector embedding via OpenAI `text-embedding-3-small` and stores it in PostgreSQL via `pgvector`.

**Request Payload:**
```json
{
  "category": "backend",
  "claim_text": "Architected an event-driven Redis caching layer cutting API latency by 65%.",
  "technical_tags": ["Redis", "FastAPI", "Caching"]
}
```

#### `DELETE /api/vault/{id}`
Deletes a vault item and cascades the deletion of its associated vector index.

---

### 2.4 System Health (`/health`)

#### `GET /health`
Returns container health status and database connectivity for Kubernetes and Render health-check probes.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "1.0.0"
}
```
