"""
Seed realistic demo applications across all Kanban stages for testing and demonstration.
"""
import uuid
from datetime import datetime, timezone, timedelta
from db.session import SessionLocal
from db.models import Application, ApplicationStatus, EventSource, PipelineEvent, ResumeSnapshot

def seed_demo():
    db = SessionLocal()
    try:
        # Clear existing applications
        db.query(ResumeSnapshot).delete()
        db.query(PipelineEvent).delete()
        db.query(Application).delete()
        db.commit()

        now = datetime.now(timezone.utc)

        demo_apps = [
            {
                "company_name": "Swiggy",
                "canonical_company_name": "swiggy",
                "role_title": "Backend Engineer - SDE II",
                "source_platform": "Naukri",
                "status": ApplicationStatus.OA_PENDING,
                "applied_at": now - timedelta(days=4),
                "location": "Bengaluru, India",
                "tech_stack": ["Python", "Kafka", "PostgreSQL"],
                "deadline": now + timedelta(days=2, hours=5),
                "job_desc": "High-throughput order processing and real-time delivery routing services using Python, Kafka, and Redis.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=4),
                        "raw_payload": "Application submitted via Naukri portal for SDE-II Backend role.",
                        "note": "Pasted job description into New Drop.",
                    },
                    {
                        "to_status": ApplicationStatus.OA_PENDING,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=1),
                        "deadline": now + timedelta(days=2, hours=5),
                        "raw_payload": "From: no-reply@hackerrank.com\nSubject: Swiggy SDE-II Online Assessment Invitation",
                        "note": "Online assessment received via HackerRank (90 mins, 2 algorithmic questions).",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Senior Backend Engineer\n\n"
                    "**Email:** engineer@example.com | **Location:** Bengaluru | **Portfolio:** github.com/candidate\n\n"
                    "## Summary\n"
                    "Backend systems engineer specializing in high-throughput distributed architectures, event-driven streaming with Kafka, and optimized relational databases.\n\n"
                    "## Experience\n"
                    "- Engineered order settlement pipeline handling 10,000+ RPS with p99 latency < 45ms.\n"
                    "- Architected distributed message consumer using Kafka and Redis cluster caching.\n"
                    "- Designed PostgreSQL schemas with automated partition pruning for multi-terabyte datasets.\n"
                ),
            },
            {
                "company_name": "Razorpay",
                "canonical_company_name": "razorpay",
                "role_title": "Senior Platform Engineer",
                "source_platform": "LinkedIn",
                "status": ApplicationStatus.APPLIED,
                "applied_at": now - timedelta(days=2),
                "location": "Bengaluru, India",
                "tech_stack": ["Go", "Kubernetes", "gRPC"],
                "job_desc": "Scale financial transaction processing engines and core payment gateway infra.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=2),
                        "raw_payload": "Submitted direct application via LinkedIn Easy Apply.",
                        "note": "Application submitted for Payment Gateway Platform team.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Platform & Distributed Systems\n\n"
                    "**Email:** candidate@example.com | **Location:** Bengaluru\n\n"
                    "## Core Competencies\n"
                    "Golang, Distributed Transactions, Kubernetes, gRPC, PostgreSQL, Financial Tech.\n\n"
                    "## Key Highlights\n"
                    "- Built fault-tolerant ledger reconciling millions of transactions with double-entry idempotency.\n"
                    "- Reduced API gateway latency by 35% via HTTP/2 and gRPC connection multiplexing.\n"
                ),
            },
            {
                "company_name": "Zerodha",
                "canonical_company_name": "zerodha",
                "role_title": "Systems Software Engineer",
                "source_platform": "Direct",
                "status": ApplicationStatus.APPLIED,
                "applied_at": now - timedelta(hours=14),
                "location": "Remote / Bengaluru",
                "tech_stack": ["Go", "PostgreSQL", "Nginx"],
                "job_desc": "Build ultra-low latency trading execution tools and real-time market data feed handlers.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(hours=14),
                        "raw_payload": "Submitted directly to Zerodha engineering careers email.",
                        "note": "Sent tailored resume highlighting performance profiling and Go internals.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Systems Engineer\n\n"
                    "## Focus\n"
                    "High-performance concurrent systems, low memory footprint, minimal latency overhead.\n\n"
                    "## Engineering Highlights\n"
                    "- Profiling memory allocations using pprof, reducing GC pause times by 60% under peak load.\n"
                    "- Implemented binary protocol parser processing 50k ticks/sec with zero allocations.\n"
                ),
            },
            {
                "company_name": "Flipkart",
                "canonical_company_name": "flipkart",
                "role_title": "SDE II - Supply Chain Tech",
                "source_platform": "Gmail Auto",
                "status": ApplicationStatus.OA_PENDING,
                "applied_at": now - timedelta(days=6),
                "location": "Bengaluru, India",
                "tech_stack": ["Java", "Kafka", "MySQL"],
                "deadline": now + timedelta(days=1, hours=12),
                "job_desc": "Architect inventory fulfillment and automated warehousing workflows.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=6),
                        "raw_payload": "Applied via Flipkart Careers portal.",
                        "note": "Initial application logged.",
                    },
                    {
                        "to_status": ApplicationStatus.OA_PENDING,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=2),
                        "deadline": now + timedelta(days=1, hours=12),
                        "raw_payload": "From: talent@flipkart.com\nSubject: Flipkart Online Assessment Round 1",
                        "note": "Automated email ingestion detected OA deadline.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Backend & Supply Chain\n\n"
                    "## Technical Summary\n"
                    "Java 17, Spring Boot, Apache Kafka, Distributed Caching, High-Scale Inventory Systems.\n\n"
                    "- Designed warehouse dispatch sequencing algorithm that improved bin packing efficiency by 18%.\n"
                    "- Built asynchronous event pipeline handling batch catalog synchronization across 5 regions.\n"
                ),
            },
            {
                "company_name": "Atlassian",
                "canonical_company_name": "atlassian",
                "role_title": "Backend Engineer II (Jira Cloud)",
                "source_platform": "LinkedIn",
                "status": ApplicationStatus.INTERVIEW_ROUND,
                "applied_at": now - timedelta(days=18),
                "location": "Remote, India",
                "tech_stack": ["Java", "AWS", "Microservices"],
                "deadline": now + timedelta(days=3, hours=2),
                "job_desc": "Scale Jira Cloud distributed backend to support enterprise tenancies with zero downtime.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=18),
                        "raw_payload": "Applied via LinkedIn.",
                        "note": "Referral application submitted.",
                    },
                    {
                        "to_status": ApplicationStatus.OA_PENDING,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=14),
                        "raw_payload": "HackerRank coding test completed with 100% test pass rate.",
                        "note": "OA cleared.",
                    },
                    {
                        "to_status": ApplicationStatus.INTERVIEW_ROUND,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=3),
                        "deadline": now + timedelta(days=3, hours=2),
                        "raw_payload": "From: recruiting@atlassian.com\nSubject: Atlassian — System Design Interview Confirmation",
                        "note": "System Design Round (Round 2) confirmed with Principal Architect.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Distributed Systems Engineer\n\n"
                    "## Highlights\n"
                    "- Designed distributed rate limiter protecting multi-tenant microservices from cascading failures.\n"
                    "- Migrated monolithic service to event-driven microservices on AWS ECS with zero downtime.\n"
                ),
            },
            {
                "company_name": "Postman",
                "canonical_company_name": "postman",
                "role_title": "SDE II - API Ecosystem",
                "source_platform": "Naukri",
                "status": ApplicationStatus.INTERVIEW_ROUND,
                "applied_at": now - timedelta(days=12),
                "location": "Bengaluru, India",
                "tech_stack": ["Node.js", "TypeScript", "Redis"],
                "job_desc": "Build developer-facing collaboration tools and real-time WebSocket protocol runners.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=12),
                        "raw_payload": "Applied via Naukri alert.",
                        "note": "Applied for API Ecosystem team.",
                    },
                    {
                        "to_status": ApplicationStatus.INTERVIEW_ROUND,
                        "source": EventSource.MANUAL_OVERRIDE,
                        "created_at": now - timedelta(days=4),
                        "raw_payload": "Recruiter phone screen passed. Scheduled Technical Machine Coding round.",
                        "note": "Technical screen scheduled.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — API Platforms & Full-Stack\n\n"
                    "## Skills\n"
                    "Node.js, TypeScript, WebSockets, Redis, OpenAPI specifications, Developer Tooling.\n\n"
                    "- Implemented WebSocket multiplexer managing 50,000+ concurrent active editor sessions.\n"
                    "- Built schema validation middleware validating 10M+ daily payloads with negligible latency.\n"
                ),
            },
            {
                "company_name": "Hasura",
                "canonical_company_name": "hasura",
                "role_title": "Backend Engineer - Engine Team",
                "source_platform": "Direct",
                "status": ApplicationStatus.OFFER,
                "applied_at": now - timedelta(days=28),
                "location": "Remote",
                "tech_stack": ["Go", "GraphQL", "PostgreSQL"],
                "job_desc": "Design instant GraphQL compiler engine and multi-tenant database connectors.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=28),
                        "raw_payload": "Direct application via careers page.",
                        "note": "Initial submission.",
                    },
                    {
                        "to_status": ApplicationStatus.INTERVIEW_ROUND,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=14),
                        "raw_payload": "Completed 4 technical rounds: Coding, Architecture, Deep Dive, Cultural Fit.",
                        "note": "All interview stages completed with strong hire ratings.",
                    },
                    {
                        "to_status": ApplicationStatus.OFFER,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=2),
                        "raw_payload": "From: people@hasura.io\nSubject: Official Offer of Employment — Hasura",
                        "note": "Offer extended! Competitive compensation package and equity grant.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Core Engine & Systems\n\n"
                    "## Summary\n"
                    "Passionate compiler and distributed engine developer with deep database internals knowledge.\n\n"
                    "- Engineered query translation layer reducing AST traversal complexity from O(n^2) to O(n).\n"
                    "- Contributed to open-source database connector ecosystem with 2,000+ GitHub stars.\n"
                ),
            },
            {
                "company_name": "Meesho",
                "canonical_company_name": "meesho",
                "role_title": "SDE II - Catalog Ingestion",
                "source_platform": "Gmail Auto",
                "status": ApplicationStatus.REJECTED,
                "applied_at": now - timedelta(days=24),
                "location": "Bengaluru, India",
                "tech_stack": ["Python", "Spark", "AWS"],
                "job_desc": "Scale product catalog indexing and batch item deduplication pipelines.",
                "timeline": [
                    {
                        "to_status": ApplicationStatus.APPLIED,
                        "source": EventSource.MANUAL_DROP,
                        "created_at": now - timedelta(days=24),
                        "raw_payload": "Applied via Naukri mobile quick-apply.",
                        "note": "Catalog team application.",
                    },
                    {
                        "to_status": ApplicationStatus.REJECTED,
                        "source": EventSource.GMAIL_WORKER,
                        "created_at": now - timedelta(days=7),
                        "raw_payload": "From: careers@meesho.com\nSubject: Update regarding your application to Meesho",
                        "note": "Position put on hold due to headcount realignment.",
                    },
                ],
                "resume": (
                    "# Candidate Profile — Big Data & Ingestion\n\n"
                    "## Highlights\n"
                    "- Scaled daily product catalog ingestion pipeline processing 20M+ items with Apache Spark.\n"
                    "- Implemented MinHash LSH deduplication reducing duplicate listing catalog clutter by 28%.\n"
                ),
            },
        ]

        for app_data in demo_apps:
            app = Application(
                id=uuid.uuid4(),
                company_name=app_data["company_name"],
                canonical_company_name=app_data["canonical_company_name"],
                role_title=app_data["role_title"],
                source_platform=app_data["source_platform"],
                current_status=app_data["status"],
                applied_at=app_data["applied_at"],
                location=app_data["location"],
                primary_tech_stack=app_data["tech_stack"],
                job_description_raw=app_data["job_desc"],
            )
            db.add(app)
            db.flush()

            # Add resume snapshot
            snap = ResumeSnapshot(
                id=uuid.uuid4(),
                application_id=app.id,
                markdown_content=app_data["resume"],
                retrieved_vault_ids=[],
                is_active=True,
                created_at=app_data["applied_at"],
            )
            db.add(snap)

            # Add timeline events
            for ev in app_data["timeline"]:
                event = PipelineEvent(
                    id=uuid.uuid4(),
                    application_id=app.id,
                    to_status=ev["to_status"],
                    source=ev["source"],
                    detected_deadline=ev.get("deadline"),
                    raw_payload=ev["raw_payload"],
                    resolution_note=ev["note"],
                    created_at=ev["created_at"],
                )
                db.add(event)

        db.commit()
        print(f"Successfully seeded {len(demo_apps)} demo applications with timeline events and resumes!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding demo applications: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_demo()
