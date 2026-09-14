# Autonomous Career Pipeline Engine (JobTracker)

An event-driven, agentic career pipeline system featuring automated ATS email triage, LangGraph state progression, grounded RAG resume snapshots, and a lightweight Streamlit control surface.

## Documentation & Blueprints

- 📘 **[System Design Document](./docs/SYSTEM_DESIGN.md)**: Full architecture specification, component interactions, PostgreSQL DDL schema, LangGraph state machine flow, CUJs, and DigitalOcean deployment guide.
- ⏱️ **[3-Week Build Timeline & Task Flow](./docs/BUILD_TIMELINE.md)**: Day-by-day implementation roadmap (Days 1–21), daily deliverables, acceptance criteria, scope protection guidelines, and risk mitigations.
- 🖼️ **[Architecture & Diagram Assets](./docs/assets/)**: High-resolution diagrams for system topology, LangGraph state machine, database schema, deployment, and project Gantt chart.

## Quick Architecture Summary

```
[User Browser] ──► [Caddy 2 (TLS :80/:443)] ──► [Streamlit UI (:8501)]
                                                        │
                                                        ▼
                                                [FastAPI Internal]
                                                   ├── Extraction Engine (Instructor)
                                                   ├── Grounded RAG (pgvector)
                                                   └── State Controller
                                                        ▲
[Gmail API] ──► [Background Worker (LangGraph)] ────────┤
                   (APScheduler every 15m)              ▼
                                                [PostgreSQL 16 DB]
```
