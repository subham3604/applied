# Autonomous Career Pipeline Engine (JobTracker)

An event-driven, agentic career pipeline system featuring automated ATS email triage, LangGraph state progression, grounded RAG resume snapshots, and a lightweight Streamlit control surface.

## Documentation & Blueprints

- 📘 **[System Design Document](./docs/SYSTEM_DESIGN.md)**: Full architecture specification, component interactions, PostgreSQL DDL schema, LangGraph state machine flow, CUJs, and DigitalOcean deployment guide.
- ⏱️ **[3-Week Build Timeline & Task Flow](./docs/BUILD_TIMELINE.md)**: Day-by-day implementation roadmap (Days 1–21), daily deliverables, acceptance criteria, scope protection guidelines, and risk mitigations.
- 🧪 **[Automated Testing Strategy](./docs/TESTING_STRATEGY.md)**: Architectural test matrix, unit test specifications, anti-hallucination guard assertions, and evaluation harness guide.
- 📊 **[Model Evaluation & Adversarial Hardening Report](./docs/EVALUATION_REPORT.md)**: Comprehensive empirical evaluation on 73 real-world samples, 16 adversarial attacks, model hardening techniques, and benchmark results.
- 🖼️ **[Architecture & Diagram Assets](./docs/assets/)**: High-resolution diagrams for system topology, LangGraph state machine, database schema, deployment, and project Gantt chart.

## Evaluation Benchmark & Portfolio Metrics (Day 19)

The career extraction and classification pipeline was evaluated against a rigorous **73-sample real-world dataset** (`tests/eval_data/`) annotated with ground-truth labels (`tests/ground_truth.json`). The dataset comprises authentic candidate correspondence harvested from Gmail, enterprise ATS records (Workday, Greenhouse, Lever, Ashby, HackerRank, Codility), and **16 high-capacity adversarial traps** (EdTech course offers, post-interview surveys, inbound vs outbound referrals, unsubmitted drafts, and offer rescissions).

### Benchmark Results

| Metric | Target Threshold | **Achieved Benchmark** | Evaluation Scope / Notes |
| :--- | :---: | :---: | :--- |
| **Stage Classification Accuracy** | $\ge 90.0\%$ | **`92.59%`** | Exact canonical match (`APPLICATION_RECEIVED`, `OA_RECEIVED`, `INTERVIEW_INVITE`, `REJECTED`) |
| **Company Extraction Precision** | $\ge 93.0\%$ | **`100.00%`** | Extracted employer matches ground truth (54/54 relevant samples) |
| **Relevance Gate Precision** | $\ge 95.0\%$ | **`98.15%`** | Precision against noise, newsletters, OTPs, and promotional traps |
| **Relevance Gate Recall** | — | **`98.15%`** | 53 of 54 genuine application emails correctly admitted |
| **Adversarial Defense Rate** | $\ge 85.0\%$ | **`93.75%`** | 15 of 16 deceptive edge-case traps correctly neutralized |

### Reproduce the Benchmark

```bash
# Run the complete Day 19 evaluation benchmark runner
.venv/bin/pytest tests/test_extraction_pipeline.py -s -v
```

---

## Quick Architecture Summary

```
[User Browser] ──► [Caddy 2 (TLS :80/:443)] ──► [React 19 + Vite Frontend (:5173)]
                                                        │
                                                        ▼
                                                [FastAPI Backend (:8000)]
                                                   ├── Extraction Engine (Instructor / gpt-4o-mini)
                                                   ├── Grounded RAG (pgvector cosine similarity)
                                                   └── State Controller & Entity Resolution
                                                        ▲
[Gmail API] ──► [Background Worker (LangGraph)] ────────┤
                   (APScheduler periodic polling)       ▼
                                                [PostgreSQL 16 DB (:5433)]
```
