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

### 2.1 Pipeline Processing (`/api/pipeline`)

#### `POST /api/pipeline/single-drop`
Performs end-to-end processing of a raw job description: extracts core requirements, queries the Master Experience Vault using cosine similarity, validates claims, and creates a new application record in the `APPLIED` state.

**Request Payload:**
```json
{
  "company_name": "Stripe",
  "job_title": "Backend Software Engineer",
  "job_description_raw": "We are seeking a backend engineer experienced in distributed systems, Java/Python, and PostgreSQL..."
}
```

**Response Payload (200 OK):**
```json
{
  "application_id": 42,
  "company_name": "Stripe",
  "job_title": "Backend Software Engineer",
  "current_stage": "APPLIED",
  "matched_bullets_count": 4,
  "hallucination_check": "PASSED"
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
