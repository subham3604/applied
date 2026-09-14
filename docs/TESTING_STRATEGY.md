# JobTracker — Automated Testing Strategy & Test Suite Map

> **Scope:** Unit tests, integration tests, hallucination guardrails, and evaluation harnesses  
> **Framework:** `pytest`, `pytest-asyncio`  
> **Status:** Active (initialized in Day 2)

---

## 1. Testing Philosophy

The Autonomous Career Pipeline Engine blends **probabilistic AI processing** (LLMs, embeddings, fuzzy matching) with **deterministic business rules** (state machine DAG, immutable audit trails, relational schemas).

Our test strategy is structured to prove system reliability across three dimensions:
1. **Deterministic Guardrails:** Proving the AI cannot violate candidate facts or hallucinate technologies.
2. **State Machine Correctness:** Proving that application status transitions strictly conform to the hiring DAG.
3. **Data Integrity:** Proving database cascade constraints, vector indexes, and audit logging function without data loss.

---

## 2. Test Suite Matrix by Architectural Section

| # | Section / Component | Test File | Primary Focus | Timeline Phase |
|---|---|---|---|---|
| **1** | **Database & Data Integrity** | `tests/test_db_models.py` | Schema constraints, cascade deletes, `pgvector` queries, `worker_config` | **Day 2 (Done ✅)** |
| **2** | **Extraction Engine** | `tests/test_extraction.py` | Instructor + Pydantic schema validation on noisy JD text dumps | **Day 3** |
| **3** | **Self-Repair & Circuit Breaker** | `tests/test_self_repair.py` | Max 3 retries on schema errors, structured failure response (no crash) | **Day 4** |
| **4** | **RAG Engine & Embeddings** | `tests/test_rag_engine.py` | Cosine similarity ranking, top-k retrieval relevance, dimension checks | **Day 5** |
| **5** | **Anti-Hallucination Guard** | `tests/test_hallucination_guard.py` | Deterministic token cross-check, rejection of unretrieved technologies | **Day 6** |
| **6** | **Phase 1 Integration** | `tests/test_phase1.py` | End-to-end: JD in → Extract → RAG → Guard → Snapshot saved to DB | **Day 7** |
| **7** | **Two-Layer Email Filter** | `tests/test_email_filter.py` | Gmail query construction, negative subject patterns, Node 0 relevance gate | **Days 8–9** |
| **8** | **Entity Resolution Chain** | `tests/test_entity_resolution.py` | Levenshtein normalization, multi-role matching, date proximity, AMBIGUOUS | **Day 10** |
| **9** | **State Machine DAG** | `tests/test_state_machine.py` | Valid transitions, repeating interview rounds, `APPLICATION_RECEIVED` deduplication | **Day 11** |
| **10** | **Manual Drop & Force Override** | `tests/test_state_controller.py` | Portal update text extraction, `MANUAL_OVERRIDE` DAG bypass | **Day 13** |
| **11** | **Phase 2 Integration** | `tests/test_phase2.py` | End-to-end automated email processing through LangGraph into PostgreSQL | **Day 14** |
| **12** | **ATS Ground-Truth Eval Harness** | `tests/test_extraction_pipeline.py` | 30+ ATS email test suite calculating precision, accuracy, and recovery metrics | **Days 18–19** |

---

## 3. Detailed Breakdown of Test Sections

### Section 1: Database & Data Integrity (`tests/test_db_models.py`)
- **Status:** **Implemented & Passing (3/3)**
- **Test Scenarios:**
  - `test_create_application_and_cascade_delete`: Creating an application with linked resume snapshot and pipeline event, then deleting the application to verify foreign key cascade deletions (`ON DELETE CASCADE`).
  - `test_worker_config_key_value`: Storing and reading key-value state (e.g., `last_checked_at`) to ensure persistent worker state across container restarts.
  - `test_master_experience_vault_vector_similarity`: Native SQL cosine distance query (`<=>`) on 1536-dimensional vectors using `pgvector` and IVFFlat index.

---

### Section 2: Extraction Service (`tests/test_extraction.py`)
- **Target File:** `web/services/extraction.py`
- **Test Scenarios:**
  - **Clean JD Parsing:** Extracts `company_name`, `role_title`, `primary_tech_stack`, `experience_required_yrs`, `location`, and `source_platform`.
  - **Noisy Portal Dumps:** Handles raw unstructured dumps from Naukri, LinkedIn, and company career pages.
  - **Explicit Role Assertion:** Asserts `role_title` is extracted only if explicitly named; verifies `role_title` returns `None` when vague (preventing LLM hallucination).

---

### Section 3: Self-Repair Loop & Circuit Breaker (`tests/test_self_repair.py`)
- **Target File:** `web/services/extraction.py`
- **Test Scenarios:**
  - **Automated Repair:** Intentionally feeds incomplete JSON or sparse text; asserts that validation errors are fed back into correction prompts (up to 3 retries).
  - **Circuit Breaker:** Feeds completely unparseable input; asserts that after 3 retries the system returns a structured error object without raising an uncaught exception.

---

### Section 4: RAG Engine & Cosine Retrieval (`tests/test_rag_engine.py`)
- **Target File:** `web/services/rag_engine.py`
- **Test Scenarios:**
  - **Semantic Relevance:** Given a backend JD (Python, PostgreSQL, Redis), top-5 retrieved bullets must belong to backend/distributed systems, not frontend or DevOps.
  - **Dimension & Normalization:** Vector dimensions match 1536, and cosine scores fall strictly between -1.0 and 1.0.

---

### Section 5: Anti-Hallucination Guardrail (`tests/test_hallucination_guard.py`)
- **Target File:** `web/services/rag_engine.py`
- **Test Scenarios:**
  - **Grounded Resume Verification:** Generates resume snapshot from retrieved bullets; asserts all mentioned technical terms exist in source vault bullets.
  - **Temptation Injection:** Prompts the LLM with temptation ("include Kafka even if not in source"); asserts the guard detects Kafka, flags the violation, and triggers regeneration.

---

### Section 6: Entity Resolution Engine (`tests/test_entity_resolution.py`)
- **Target File:** `worker/entity_resolution.py`
- **Test Scenarios:**
  - **Level 1 (Fuzzy Match):** "Zomato Media Private Limited" matches "Zomato" (score ≥ 0.85).
  - **Level 2 (Semantic Arbitration):** Legal entity "Bundl Technologies Pvt Ltd" resolves to "Swiggy" via LLM arbitration.
  - **Level 3 (Date Proximity):** Email missing role with same company applied within 24 hours matches with `LOW` confidence; gap ≥ 24 hours flags as `AMBIGUOUS`.
  - **Zero Matches:** Unmatched company returns `CREATE_NEW`.

---

### Section 7: State Machine DAG Transitions (`tests/test_state_machine.py`)
- **Target File:** `web/services/state_controller.py` & LangGraph nodes
- **Test Scenarios:**
  - **Valid DAG Edges:** `APPLIED → OA_PENDING`, `APPLIED → INTERVIEW_ROUND`, `INTERVIEW_ROUND → OFFER`.
  - **Self-Loop (Multiple Rounds):** `INTERVIEW_ROUND → INTERVIEW_ROUND` preserves status and appends a new `pipeline_events` audit row.
  - **`APPLICATION_RECEIVED` Confirmation:** Duplicate confirmation email preserves status as `APPLIED` and logs an audit record.
  - **Invalid Transitions:** Backward transitions (e.g. `REJECTED → APPLIED`) are rejected.
  - **Force Override:** `MANUAL_OVERRIDE` bypasses validation for manual user corrections.

---

### Section 8: Offline Evaluation Harness (`tests/test_extraction_pipeline.py`)
- **Target Directory:** `tests/eval_data/`
- **Test Scenarios:**
  - Evaluates against a curated ground-truth dataset of 30+ real ATS emails (Greenhouse, Lever, Workday, Naukri).
  - Produces quantitative portfolio metrics:
    - **Stage Classification Accuracy** (Target: ≥ 90%)
    - **Entity Extraction Precision** (Target: ≥ 93%)
    - **Schema Repair Recovery Rate** (Target: ≥ 85%)

---

## 4. How to Run Tests

```bash
# Run all unit tests
.venv/bin/pytest -v

# Run a specific test module
.venv/bin/pytest tests/test_db_models.py -v

# Run with test coverage report
.venv/bin/pytest --cov=db --cov=web/services --cov=worker -v
```
