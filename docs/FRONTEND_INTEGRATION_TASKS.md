# Frontend Integration & Connection Tasks

> **Context:** Phase 1 (Extraction, RAG, Ingestion) and Phase 2 (LangGraph Agent, Gmail Worker, State DAG) are complete.  
> The backend HTTP service (`web/main.py`) is written in FastAPI with complete serializers matching the TypeScript types in `pixel-perfect-render-1659`.  
> This document tracks the remaining tasks to connect the React (Vite + Tailwind) frontend to the FastAPI backend and deploy both tiers.

---

## Architecture Flow

```
[React SPA on Vercel]
       │
       │ HTTP / JSON via fetch / TanStack Query
       │ Base URL: VITE_API_URL (e.g. https://api.yourdomain.com)
       ▼
[Caddy 2 Reverse Proxy on DigitalOcean] (:80 / :443)
       │
       ▼
[FastAPI Backend :8000] (web/main.py)
       ├── GET  /api/metrics                        (Stats bar)
       ├── GET  /api/applications                   (Kanban board)
       ├── GET  /api/applications/{id}              (Detail drawer)
       ├── POST /api/applications/parse             (JD drop parsing & RAG)
       ├── PATCH /api/applications/{id}/resume      (Confirm edited resume)
       ├── PATCH /api/applications/{id}/status      (Direct status override)
       └── POST /api/applications/{id}/text-update (Portal snippet update)
```

---

## 1. Frontend Tasks (`pixel-perfect-render-1659` Repo)

### [x] Task 1.1: Create Central API Client (`src/lib/api.ts`)
Create a typed API client so routes do not have hardcoded fetch strings.

```typescript
// src/lib/api.ts
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function fetchMetrics() {
  const res = await fetch(`${API_BASE}/api/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.json();
}

export async function fetchApplications() {
  const res = await fetch(`${API_BASE}/api/applications`);
  if (!res.ok) throw new Error("Failed to fetch applications");
  return res.json();
}

export async function parseJD(jd_text: string, source_platform: string = "Direct") {
  const res = await fetch(`${API_BASE}/api/applications/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jd_text, source_platform }),
  });
  if (!res.ok) throw new Error("Failed to parse JD");
  return res.json();
}

export async function updateResume(appId: string, markdown: string) {
  const res = await fetch(`${API_BASE}/api/applications/${appId}/resume`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown }),
  });
  if (!res.ok) throw new Error("Failed to update resume");
  return res.json();
}

export async function overrideStatus(appId: string, newStatus: string, note: string = "") {
  const res = await fetch(`${API_BASE}/api/applications/${appId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_status: newStatus, note }),
  });
  if (!res.ok) throw new Error("Failed to update status");
  return res.json();
}

export async function updatePortalText(appId: string, raw_text: string) {
  const res = await fetch(`${API_BASE}/api/applications/${appId}/text-update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text }),
  });
  if (!res.ok) throw new Error("Failed to submit portal text update");
  return res.json();
}
```

---

### [x] Task 1.2: Connect Kanban Dashboard (`src/routes/index.tsx`)
- **Replace Mock Data:** Replace imports of static `APPLICATIONS` and hardcoded `stats` array with dynamic state fetched via `fetchApplications()` and `fetchMetrics()`.
- **Loading & Empty States:** Show skeleton cards (`components/ui/skeleton.tsx`) while loading.
- **Card Click:** Wire clicking an `AppCard` to set the selected `Application` object in `active` state to open `DetailDrawer`.
- **Search & Filter:** Ensure the existing search bar and `FILTERS` ("All", "High Priority", "Active", "Archived") operate on the fetched array.

---

### [x] Task 1.3: Connect New Application Drop (`src/routes/new-drop.tsx`)
- **Action Trigger:** On clicking "🚀 Parse & Tailor Resume":
  1. Set `loading = true`.
  2. Call `parseJD(jdText, selectedPlatform)`.
  3. On success:
     - Set metadata card values: `company`, `role`, `stack`, `location`.
     - Populate Markdown resume editor state with returned `resume`.
     - Store returned `application_id`.
  4. Show toast notification via `sonner`.
- **Save & Confirm Action:** On clicking "Confirm & Save to Pipeline":
  1. If user edited the markdown: call `updateResume(applicationId, resumeText)`.
  2. Navigate back to `/` (dashboard).

---

### [ ] Task 1.4: Connect Detail Drawer (`src/components/relay/DetailDrawer.tsx`)
- **Direct Override Tab:**
  - Map dropdown selection (e.g. `OA_PENDING`, `INTERVIEW_ROUND`, `OFFER`, `REJECTED`, `WITHDRAWN`) and optional note input.
  - On submit: call `overrideStatus(app.id, newStatus, note)`.
  - Toast success and trigger parent board refresh.
- **Paste Portal Snippet Tab:**
  - Textarea for raw recruiter / portal update message.
  - On submit: call `updatePortalText(app.id, rawText)`.
  - Toast classification result (e.g. "Classified as INTERVIEW_INVITE") and refresh board.
- **Copy Resume Button:** Wire click to copy `app.resume` markdown content to clipboard via `navigator.clipboard.writeText`.

---

### [ ] Task 1.5: Configure Frontend Environment Variables (Vercel)
In the Vercel Project Dashboard:
- Add `VITE_API_URL`:
  - **Local development:** `http://localhost:8000` (in `.env.local`)
  - **Production:** `https://api.yourdomain.com` (in Vercel Project Settings → Environment Variables)

---

## 2. Backend Tasks (`JobTracker` Workspace)

### [x] Task 2.1: Update `web/Dockerfile` to FastAPI
Modify `web/Dockerfile` so the `web` container runs the FastAPI application via `uvicorn` instead of Streamlit:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build-essential for C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir uvicorn fastapi

COPY . .

EXPOSE 8000

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### [x] Task 2.2: Add Integration Test Suite (`tests/test_api_endpoints.py`)
Verify that all 7 endpoints return HTTP 200 and exact matching schemas expected by the React frontend:
1. `GET /api/metrics` → returns `{ total, applied, pending_oa, active_interviews, offers, rejected }`
2. `GET /api/applications` → returns array matching frontend `Application` interface
3. `POST /api/applications/parse` → handles sample JD and returns structured fields
4. `PATCH /api/applications/{id}/status` → applies `MANUAL_OVERRIDE` and returns new status + stage
5. `PATCH /api/applications/{id}/resume` → updates snapshot content
6. `POST /api/applications/{id}/text-update` → classifies text and creates `MANUAL_DROP` event

---

### [ ] Task 2.3: Production CORS Origin Whitelist
In `web/main.py`:
- Update `allow_origins` to include the final production Vercel domain once deployed:
  ```python
  allow_origins=[
      "http://localhost:5173",
      "https://relay-*.vercel.app",
      "https://relay.yourdomain.com",
  ]
  ```

---

## 3. End-to-End Verification Runbook

### Step 1: Run Backend Locally
```bash
cd /Users/subham/Desktop/JobTracker
source .venv/bin/activate
uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```
Check health:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/metrics
```

### Step 2: Run Frontend Locally
```bash
cd <path-to>/pixel-perfect-render-1659
echo "VITE_API_URL=http://localhost:8000" > .env.local
npm install
npm run dev
```
Open `http://localhost:5173` in browser.

### Step 3: Verify Critical User Journeys
1. **CUJ-1 Test:** Navigate to `/new-drop`. Paste sample JD from Naukri/LinkedIn. Click "Parse & Tailor Resume". Verify metadata card populates and Markdown resume appears. Click "Confirm & Save to Pipeline". Check that card appears on `/` board.
2. **CUJ-4 Test:** Click newly created card. Open Detail Drawer. Under "Direct Override", change status to `OA_PENDING` with note "Assessment link received". Click update. Verify card moves to "OA Pending" column and timeline shows `Override` badge.
3. **CUJ-3 Test:** In Detail Drawer, under "Paste Portal Snippet", paste: *"Congratulations, you have been shortlisted for technical interview on Google Meet."* Verify status transitions to `INTERVIEW_ROUND` with `Manual Drop` badge.
