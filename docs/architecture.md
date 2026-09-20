# System Architecture & Design Decisions

This document details the architectural blueprint, component interactions, deterministic state machine invariants, RAG retrieval mechanics, and failure recovery protocols of the Applied career pipeline platform.

---

## 1. System Architecture

```mermaid
graph TD
    Client["Candidate Browser (React 19 on Vercel)"]
    FastAPI["FastAPI Backend Server (Render Container)"]
    Worker["Autonomous Triage Worker (Daily Cron)"]
    Gmail["Google Gmail API (OAuth2)"]
    DB[("Supabase PostgreSQL 16 + pgvector")]
    OpenAI["OpenAI API (gpt-4o-mini + text-embedding-3-small)"]

    Client -->|HTTPS REST| FastAPI
    
    Gmail -->|Daily Ingestion| Worker
    Worker -->|Tier-1 Regex Pre-Filter| Worker
    Worker -->|Tier-2 LangGraph DAG| OpenAI
    Worker -->|Persist State and Audit Events| DB
    Worker -->|Queue Ambiguous Inbound Items| DB

    FastAPI -->|Extract JD and Score Requirements| OpenAI
    FastAPI -->|Cosine Similarity Search| DB
    FastAPI -->|Application CRUD and Overrides| DB
    FastAPI -->|Triage Resolution and Deck API| DB
    FastAPI <-->|Live Updates and Triage Deck| Client
```

---

## 2. Core Subsystems

### 2.1 Autonomous 2-Tier ATS Ingestion Pipeline
The background ingestion pipeline continuously processes raw inbound recruiter correspondence while safeguarding downstream LLM token quotas:

```
Raw Inbound Email ──► [Tier-1: Regex Pre-Filter] ──► (Reject: Newsletters, OTPs, Spam)
                             │
                             ▼ (Relevant Candidate)
                      [Tier-2: LangGraph 4-Node DAG]
                             │
                             ├── Node 0: Relevance Gate (CoT Pydantic)
                             ├── Node 1: Hierarchical Entity Extractor
                             ├── Node 2: Stage Classifier
                             └── Node 3: State Reconciler & DB Committer
                                   ├── High Confidence Match ──► Advance Application Status + Log Event
                                   └── Ambiguous / Multi-Match ──► Inbound Triage Queue (inbound_triage_items)
```

* **Tier-1 Regex Pre-Filter:** Drops commercial newsletters, marketing promotions, OTPs, and irrelevant transactional receipts in <5ms using sender headers and subject line heuristics.
* **Tier-2 LangGraph Classification DAG:** Evaluates surviving emails through a 4-node state machine enforcing Chain-of-Thought (CoT) reasoning via `Instructor` and Pydantic schemas.
* **5-Tier Hierarchical Entity Resolution:** Unwraps enterprise ATS redirects (`modmed@myworkday.com` $\rightarrow$ *Modernizing Medicine*), extracts employer entities from message bodies, and resolves against active pipeline records using date-proximity heuristics.

### 2.2 Deterministic Application State Machine DAG
To prevent state corruption from delayed, out-of-order, or ambiguous emails, the state controller enforces a **strictly monotonic, non-reversible DAG**:

$$\text{APPLIED} \longrightarrow \text{OA\_PENDING} \longrightarrow \text{INTERVIEW\_ROUND} \longrightarrow \text{OFFER} \;\;/\;\; \text{REJECTED}$$

* **Non-Reversible Invariants:** An application in `INTERVIEW_ROUND` will automatically reject an out-of-order confirmation email that attempts to regress its status to `APPLIED`.
* **Attention Required Inbound Triage Queue:** If an email is confirmed relevant but fails confident single-record entity resolution (e.g. candidate has multiple active roles at the same company, or the message arrives from an alias domain like *Bundl Technologies / Swiggy* without an explicit role title), it is quarantined into `inbound_triage_items` with status `PENDING`.
  * **Candidate Correlation:** The worker evaluates potential application matches using fuzzy matching and role heuristics, attaching `candidate_application_ids` as a JSONB list.
  * **Human-in-the-Loop Triaging:** The React frontend consumes `GET /api/attention` and renders an interactive stacked card deck banner atop the Kanban board. The user has 3 atomic actions:
    1. **Assign to Candidate:** `POST /api/attention/{id}/assign` advances the target application's stage, marks the triage item `RESOLVED`, and appends an immutable `PipelineEvent` with `source = GMAIL_WORKER`.
    2. **Create New Application:** `POST /api/attention/{id}/create-application` creates a new application record in the target stage, sets platform to `Inbound Email`, and logs initial provenance.
    3. **Dismiss:** `POST /api/attention/{id}/dismiss` sets item status to `DISMISSED` without mutating pipeline records.

### 2.3 Grounded RAG Resume Tailor & Anti-Hallucination Guard
When a candidate drops a raw Job Description (JD):
1. **Extraction:** The backend extracts required competencies, core tools, and experience level.
2. **Semantic Vector Search:** Queries the `master_experience_vault` using **1536-dimensional cosine embeddings** (`text-embedding-3-small`) in PostgreSQL via `pgvector`.
3. **Anti-Hallucination Verification Guard:** An automated verification check compares the generated bullet selections against source vault claims, rejecting fabricated achievements before persisting an immutable resume snapshot.

---

## 3. Key Architectural Decisions & Tradeoffs

### Modular Monolith vs. Microservices
* **Decision:** Containerized modular monolith sharing a single PostgreSQL database rather than distributed microservices.
* **Benefit:** Eliminates distributed transaction overhead, service meshes, and network serialization latency while keeping local development dead-simple.
* **Tradeoff:** Background worker shares the same database pool as the web API; mitigated by connection pooling (`pool_size=10, max_overflow=20`).

### Relational Vector Store (`pgvector`) vs. Dedicated Vector DB (Pinecone/Weaviate)
* **Decision:** Utilizing PostgreSQL 16 with the `pgvector` extension instead of an external vector database.
* **Benefit:** Ensures ACID compliance across application state and vector embeddings in a single database transaction. Zero risk of data synchronization drift.
* **Tradeoff:** Higher memory utilization on Postgres for large-scale HNSW indexes; well within capacity for candidate experience vaults (<10,000 vectors).

### Deterministic State Machine vs. Autonomous Multi-Agent Swarm
* **Decision:** Hardcoded LangGraph state transition graph rather than a fully autonomous free-form agent.
* **Benefit:** 100% predictable, testable, and auditable state transitions. Zero risk of an autonomous agent arbitrarily moving or deleting user applications.
* **Tradeoff:** Requires explicit transition rules for every edge case.

---

## 4. Failure Recovery & Self-Healing

* **Gmail Token Refresh:** Headless OAuth2 client automatically refreshes expiring tokens using stored refresh secrets without interrupting polling cycles.
* **Ambiguous Entity Isolation:** Inbound emails that fail confident entity resolution are safely parked in `inbound_triage_items` rather than hallucinating state changes or aborting the batch, allowing automated polling to complete cleanly.
* **Dead-Letter Logging:** Irrelevant emails or malformed payloads are logged to a dead-letter audit table with full headers for post-mortem debugging.
* **State Rollback:** Database writes and audit log updates are wrapped in atomic SQLAlchemy transactions; if a state transition fails verification, the transaction rolls back cleanly.

---

## 5. Security & Transport Model

* **Read-Only Scope Delegation:** The Gmail integration operates with scoped `gmail.readonly` permissions, preventing the application from sending, modifying, or deleting candidate emails.
* **Zero PII Leakage:** Tailored resumes and vector queries only process candidate-provided technical claims stored in the local vault.
* **Edge & Transport Security:** Vercel terminates TLS at the global edge network for the React frontend, while Render manages automated SSL certificates and secure container HTTPS termination for the FastAPI backend, guaranteeing encrypted transport across all boundaries.
