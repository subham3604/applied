export type Stage = "applied" | "oa" | "interview" | "offer" | "rejected";

export type Source = "Naukri" | "LinkedIn" | "Gmail Auto" | "Manual" | "Direct";

export type TimelineEvent = {
  id: string;
  title: string;
  detail: string;
  date: string;
  timestamp?: string | null;
  origin: "worker" | "manual" | "override";
  payload: string;
};

export type Application = {
  id: string;
  company: string;
  role: string;
  stage: Stage;
  source: Source;
  applied: string;
  applied_at?: string | null;
  deadline?: string;
  deadlineTone?: "warning" | "danger";
  stack: string[];
  priority?: boolean;
  location: string;
  timeline: TimelineEvent[];
  resume: string;
};

export const STAGES: { id: Stage; label: string; hint: string }[] = [
  { id: "applied", label: "Applied", hint: "Default stage" },
  { id: "oa", label: "OA Pending", hint: "Assessments / tests" },
  { id: "interview", label: "Interview Rounds", hint: "R1 · R2 · System Design" },
  { id: "offer", label: "Offer", hint: "Success" },
  { id: "rejected", label: "Rejected / Withdrawn", hint: "Archived" },
];

export const APPLICATIONS: Application[] = [
  {
    id: "swiggy-sde2",
    company: "Swiggy",
    role: "Backend Engineer - SDE II",
    stage: "oa",
    source: "Naukri",
    applied: "Applied 4d ago",
    deadline: "Due: Sep 21, 02:00 PM",
    deadlineTone: "warning",
    stack: ["Python", "Kafka", "PostgreSQL"],
    priority: true,
    location: "Bengaluru, India",
    resume:
      "# Candidate Profile — Senior Backend Engineer\n\n**Email:** engineer@example.com | **Location:** Bengaluru\n\n## Experience\n- Engineered order settlement pipeline handling 10,000+ RPS with p99 latency < 45ms.\n- Architected distributed message consumer using Kafka and Redis cluster caching.\n- Designed PostgreSQL schemas with automated partition pruning for multi-terabyte datasets.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Application submitted via Naukri portal for SDE-II Backend role.",
        date: "Sep 15, 2026",
        origin: "manual",
        payload: "Pasted job description into New Drop.",
      },
      {
        id: "e2",
        title: "OA Pending (Gmail Worker)",
        detail: "Online assessment received via HackerRank (90 mins, 2 algorithmic questions).",
        date: "Sep 18, 2026",
        origin: "worker",
        payload: "From: no-reply@hackerrank.com\nSubject: Swiggy SDE-II Online Assessment Invitation",
      },
    ],
  },
  {
    id: "razorpay-plat",
    company: "Razorpay",
    role: "Senior Platform Engineer",
    stage: "applied",
    source: "LinkedIn",
    applied: "Applied 2d ago",
    stack: ["Go", "Kubernetes", "gRPC"],
    location: "Bengaluru, India",
    resume:
      "# Candidate Profile — Platform & Distributed Systems\n\n## Core Competencies\nGolang, Distributed Transactions, Kubernetes, gRPC, PostgreSQL.\n\n## Highlights\n- Built fault-tolerant ledger reconciling millions of transactions with double-entry idempotency.\n- Reduced API gateway latency by 35% via HTTP/2 and gRPC connection multiplexing.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Submitted direct application via LinkedIn Easy Apply.",
        date: "Sep 17, 2026",
        origin: "manual",
        payload: "Application submitted for Payment Gateway Platform team.",
      },
    ],
  },
  {
    id: "zerodha-sys",
    company: "Zerodha",
    role: "Systems Software Engineer",
    stage: "applied",
    source: "Direct",
    applied: "Applied 14h ago",
    stack: ["Go", "PostgreSQL", "Nginx"],
    location: "Remote / Bengaluru",
    resume:
      "# Candidate Profile — Systems Engineer\n\n## Focus\nHigh-performance concurrent systems, low memory footprint, minimal latency overhead.\n\n## Highlights\n- Profiling memory allocations using pprof, reducing GC pause times by 60% under peak load.\n- Implemented binary protocol parser processing 50k ticks/sec with zero allocations.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Sent tailored resume highlighting performance profiling and Go internals.",
        date: "Today, 12:30 AM",
        origin: "manual",
        payload: "Submitted directly to Zerodha engineering careers email.",
      },
    ],
  },
  {
    id: "flipkart-sc",
    company: "Flipkart",
    role: "SDE II - Supply Chain Tech",
    stage: "oa",
    source: "Gmail Auto",
    applied: "Applied 6d ago",
    deadline: "Due: Sep 20, 09:00 PM",
    deadlineTone: "warning",
    stack: ["Java", "Kafka", "MySQL"],
    location: "Bengaluru, India",
    resume:
      "# Candidate Profile — Backend & Supply Chain\n\n## Technical Summary\nJava 17, Spring Boot, Apache Kafka, Distributed Caching, High-Scale Inventory Systems.\n\n- Designed warehouse dispatch sequencing algorithm that improved bin packing efficiency by 18%.\n- Built asynchronous event pipeline handling batch catalog synchronization across 5 regions.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Initial application logged via careers portal.",
        date: "Sep 13, 2026",
        origin: "manual",
        payload: "Applied via Flipkart Careers portal.",
      },
      {
        id: "e2",
        title: "OA Pending (Gmail Worker)",
        detail: "Automated email ingestion detected OA deadline.",
        date: "Sep 17, 2026",
        origin: "worker",
        payload: "From: talent@flipkart.com\nSubject: Flipkart Online Assessment Round 1",
      },
    ],
  },
  {
    id: "atlassian-cloud",
    company: "Atlassian",
    role: "Backend Engineer II (Jira Cloud)",
    stage: "interview",
    source: "LinkedIn",
    applied: "Applied 18d ago",
    deadline: "Due: Sep 22, 04:30 PM",
    deadlineTone: "warning",
    stack: ["Java", "AWS", "Microservices"],
    priority: true,
    location: "Remote, India",
    resume:
      "# Candidate Profile — Distributed Systems Engineer\n\n## Highlights\n- Designed distributed rate limiter protecting multi-tenant microservices from cascading failures.\n- Migrated monolithic service to event-driven microservices on AWS ECS with zero downtime.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Referral application submitted.",
        date: "Sep 1, 2026",
        origin: "manual",
        payload: "Applied via LinkedIn referral link.",
      },
      {
        id: "e2",
        title: "OA Pending (Gmail Worker)",
        detail: "HackerRank coding test completed with 100% pass rate.",
        date: "Sep 5, 2026",
        origin: "worker",
        payload: "Coding assessment completed.",
      },
      {
        id: "e3",
        title: "Interview Round (Gmail Worker)",
        detail: "System Design Round (Round 2) confirmed with Principal Architect.",
        date: "Sep 16, 2026",
        origin: "worker",
        payload: "From: recruiting@atlassian.com\nSubject: System Design Interview Confirmation",
      },
    ],
  },
  {
    id: "postman-api",
    company: "Postman",
    role: "SDE II - API Ecosystem",
    stage: "interview",
    source: "Naukri",
    applied: "Applied 12d ago",
    stack: ["Node.js", "TypeScript", "Redis"],
    location: "Bengaluru, India",
    resume:
      "# Candidate Profile — API Platforms & Full-Stack\n\n## Skills\nNode.js, TypeScript, WebSockets, Redis, OpenAPI specifications, Developer Tooling.\n\n- Implemented WebSocket multiplexer managing 50,000+ concurrent active editor sessions.\n- Built schema validation middleware validating 10M+ daily payloads with negligible latency.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Applied for API Ecosystem team.",
        date: "Sep 7, 2026",
        origin: "manual",
        payload: "Applied via Naukri alert.",
      },
      {
        id: "e2",
        title: "Interview Round (Manual Override)",
        detail: "Recruiter phone screen passed. Scheduled Technical Machine Coding round.",
        date: "Sep 15, 2026",
        origin: "override",
        payload: "Technical screen scheduled.",
      },
    ],
  },
  {
    id: "hasura-eng",
    company: "Hasura",
    role: "Backend Engineer - Engine Team",
    stage: "offer",
    source: "Direct",
    applied: "Applied 28d ago",
    stack: ["Go", "GraphQL", "PostgreSQL"],
    priority: true,
    location: "Remote",
    resume:
      "# Candidate Profile — Core Engine & Systems\n\n## Summary\nPassionate compiler and distributed engine developer with deep database internals knowledge.\n\n- Engineered query translation layer reducing AST traversal complexity from O(n^2) to O(n).\n- Contributed to open-source database connector ecosystem with 2,000+ GitHub stars.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Initial submission via careers portal.",
        date: "Aug 22, 2026",
        origin: "manual",
        payload: "Direct application via careers page.",
      },
      {
        id: "e2",
        title: "Interview Round (Gmail Worker)",
        detail: "Completed all technical rounds with strong hire ratings.",
        date: "Sep 5, 2026",
        origin: "worker",
        payload: "Completed Coding, Architecture, Deep Dive, and Culture interviews.",
      },
      {
        id: "e3",
        title: "Offer (Gmail Worker)",
        detail: "Offer extended! Competitive compensation package and equity grant.",
        date: "Sep 17, 2026",
        origin: "worker",
        payload: "From: people@hasura.io\nSubject: Official Offer of Employment — Hasura",
      },
    ],
  },
  {
    id: "meesho-cat",
    company: "Meesho",
    role: "SDE II - Catalog Ingestion",
    stage: "rejected",
    source: "Gmail Auto",
    applied: "Applied 24d ago",
    stack: ["Python", "Spark", "AWS"],
    location: "Bengaluru, India",
    resume:
      "# Candidate Profile — Big Data & Ingestion\n\n## Highlights\n- Scaled daily product catalog ingestion pipeline processing 20M+ items with Apache Spark.\n- Implemented MinHash LSH deduplication reducing duplicate listing catalog clutter by 28%.\n",
    timeline: [
      {
        id: "e1",
        title: "Applied (Manual Drop)",
        detail: "Catalog team application.",
        date: "Aug 26, 2026",
        origin: "manual",
        payload: "Applied via Naukri mobile quick-apply.",
      },
      {
        id: "e2",
        title: "Rejected (Gmail Worker)",
        detail: "Position put on hold due to headcount realignment.",
        date: "Sep 12, 2026",
        origin: "worker",
        payload: "From: careers@meesho.com\nSubject: Update regarding your application to Meesho",
      },
    ],
  },
];

export const SAMPLE_JD = `Backend Engineer - SDE II
Location: Bengaluru | Experience: 2-4 yrs

You will own high-throughput order and settlement services. Strong Python,
Kafka streaming, Redis caching and PostgreSQL schema design expected.`;
