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

### 2.4 Inbound Attention & Ambiguous Triage Queue (`/api/attention`)

#### `GET /api/attention`
Fetches all pending ambiguous inbound emails quarantined by the background worker, enriched with candidate application matches for 1-click human triage.

**Response Payload (200 OK):**
```json
[
  {
    "id": "c1f7a0b5-7489-4d32-bb15-5e0450db2d01",
    "source": "GMAIL_WORKER",
    "sender": "recruiting@bundltechnologies.com",
    "recipient": "candidate@gmail.com",
    "subject": "Next steps regarding your application at Bundl Technologies (Swiggy)",
    "raw_body": "Hi candidate, thank you for your application to Bundl Technologies (Swiggy)...",
    "detected_company": "Bundl Technologies",
    "detected_role": "Full Stack Engineer",
    "suggested_stage": "INTERVIEW_ROUND",
    "resolution_confidence": "AMBIGUOUS",
    "resolution_note": "Multiple active applications found under alias 'Bundl Technologies / Swiggy'. Needs user disambiguation.",
    "candidate_application_ids": ["9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"],
    "candidate_apps": [
      {
        "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "company": "Swiggy",
        "role": "Backend Engineer",
        "stage": "APPLIED",
        "applied_at": "2026-09-18T10:00:00Z"
      }
    ],
    "status": "PENDING",
    "created_at": "2026-09-20T08:00:00Z"
  }
]
```

#### `POST /api/attention/{id}/assign`
Assigns an ambiguous inbound email to an existing application, advances the application's stage, marks the triage item `RESOLVED`, and appends an immutable `PipelineEvent` audit row.

**Request Payload:**
```json
{
  "application_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "new_status": "INTERVIEW_ROUND",
  "note": "Assigned from Bundl email to Swiggy Backend Engineer"
}
```

**Response Payload (200 OK):**
```json
{
  "success": true,
  "application_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "INTERVIEW_ROUND"
}
```

#### `POST /api/attention/{id}/create-application`
Creates a new application directly from the triage item, appends initial provenance to `pipeline_events`, and marks the triage item `RESOLVED`.

**Request Payload:**
```json
{
  "company_name": "Bundl Technologies",
  "role_title": "Full Stack Engineer",
  "status": "INTERVIEW_ROUND",
  "note": "Created new record from inbound email"
}
```

**Response Payload (200 OK):**
```json
{
  "success": true,
  "application_id": "e4a2c1d0-9988-4bb1-a123-7c8d9e0f1a2b"
}
```

#### `POST /api/attention/{id}/dismiss`
Dismisses an ambiguous triage item without mutating any application records. Sets status to `DISMISSED`.

**Response Payload (200 OK):**
```json
{
  "success": true,
  "dismissed_id": "c1f7a0b5-7489-4d32-bb15-5e0450db2d01"
}
```

#### `POST /api/attention/seed-demo`
Seeds sample realistic ambiguous triage items (e.g. Bundl/Swiggy alias disambiguation, Stripe role confusion) for verification and testing.

---

### 2.5 System Health (`/health`)

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
