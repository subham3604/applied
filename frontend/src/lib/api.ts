import type { Application } from "./relay-data";

export interface PipelineMetrics {
  total: number;
  total_active: number;
  applied: number;
  pending_oa: number;
  active_interviews: number;
  offers: number;
  rejected: number;
}

export interface ParseJDResponse {
  success: boolean;
  application_id?: string;
  company?: string;
  role?: string;
  stack?: string[];
  location?: string;
  source?: string;
  resume?: string;
  guard_passed?: boolean;
  extraction_retries?: number;
  error?: string;
  circuit_broken?: boolean;
}

export interface StatusOverrideResponse {
  success: boolean;
  event_id: string;
  new_status: string;
  stage: string;
}

export interface TextUpdateResponse {
  success: boolean;
  event_id: string;
  new_status: string;
  stage: string;
}

export interface WorkerStatus {
  active: boolean;
  schedule: string;
  last_synced_at?: string | null;
  last_checked_boundary?: string | null;
  total_worker_events: number;
}

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function fetchMetrics(): Promise<PipelineMetrics> {
  const res = await fetch(`${API_BASE}/api/metrics`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch metrics: ${res.statusText}`);
  return res.json();
}

export async function fetchWorkerStatus(): Promise<WorkerStatus> {
  const res = await fetch(`${API_BASE}/api/worker/status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch worker status: ${res.statusText}`);
  return res.json();
}

export async function fetchApplications(): Promise<Application[]> {
  const res = await fetch(`${API_BASE}/api/applications`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch applications: ${res.statusText}`);
  return res.json();
}

export async function fetchApplication(appId: string): Promise<Application> {
  const res = await fetch(`${API_BASE}/api/applications/${appId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch application ${appId}: ${res.statusText}`);
  return res.json();
}

export async function parseJD(
  jd_text: string,
  source_platform: string = "Direct"
): Promise<ParseJDResponse> {
  const res = await fetch(`${API_BASE}/api/applications/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jd_text, source_platform }),
  });
  if (!res.ok) throw new Error(`Failed to parse JD: ${res.statusText}`);
  return res.json();
}

export async function updateResume(
  appId: string,
  markdown: string
): Promise<{ success: boolean; resume_snapshot_id: string }> {
  const res = await fetch(`${API_BASE}/api/applications/${appId}/resume`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown }),
  });
  if (!res.ok) throw new Error(`Failed to update resume: ${res.statusText}`);
  return res.json();
}

export async function overrideStatus(
  appId: string,
  newStatus: string,
  note: string = ""
): Promise<StatusOverrideResponse> {
  const res = await fetch(`${API_BASE}/api/applications/${appId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_status: newStatus, note }),
  });
  if (!res.ok) throw new Error(`Failed to update status: ${res.statusText}`);
  return res.json();
}

export async function updatePortalText(
  appId: string,
  raw_text: string
): Promise<TextUpdateResponse> {
  const res = await fetch(`${API_BASE}/api/applications/${appId}/text-update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text }),
  });
  if (!res.ok) throw new Error(`Failed to submit portal text update: ${res.statusText}`);
  return res.json();
}

export type VaultCategory = "WORK_EXPERIENCE" | "PROJECT" | "SKILL" | "EDUCATION";

export interface VaultBullet {
  id: string;
  category: VaultCategory;
  title: string;
  bullet_point: string;
  tech_tags: string[];
  created_at: string;
}

export interface VaultBulletCreate {
  category: VaultCategory;
  title: string;
  bullet_point: string;
  tech_tags?: string[];
}

export interface VaultBulletUpdate {
  category?: VaultCategory;
  title?: string;
  bullet_point?: string;
  tech_tags?: string[];
}

export async function fetchVaultBullets(
  category?: string,
  search?: string
): Promise<VaultBullet[]> {
  const params = new URLSearchParams();
  if (category && category !== "ALL") params.append("category", category);
  if (search && search.trim()) params.append("search", search.trim());
  const qs = params.toString() ? `?${params.toString()}` : "";

  const res = await fetch(`${API_BASE}/api/vault${qs}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch vault bullets: ${res.statusText}`);
  return res.json();
}

export async function createVaultBullet(
  data: VaultBulletCreate
): Promise<VaultBullet> {
  const res = await fetch(`${API_BASE}/api/vault`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to create bullet: ${res.statusText}`);
  }
  return res.json();
}

export async function updateVaultBullet(
  id: string,
  data: VaultBulletUpdate
): Promise<VaultBullet> {
  const res = await fetch(`${API_BASE}/api/vault/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to update bullet: ${res.statusText}`);
  }
  return res.json();
}

export async function deleteVaultBullet(
  id: string
): Promise<{ success: boolean; deleted_id: string }> {
  const res = await fetch(`${API_BASE}/api/vault/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to delete bullet: ${res.statusText}`);
  }
  return res.json();
}

export interface CandidateApp {
  id: string;
  company: string;
  role: string;
  currentStatus: string;
}

export interface AttentionItem {
  id: string;
  source: string;
  sender: string;
  recipient?: string | null;
  subject: string;
  raw_body: string;
  detected_company?: string | null;
  detected_role?: string | null;
  suggested_stage: string;
  resolution_confidence: string;
  resolution_note?: string | null;
  candidate_applications: CandidateApp[];
  status: string;
  created_at: string;
}

export async function fetchAttentionItems(includeDemo: boolean = true): Promise<AttentionItem[]> {
  const url = `${API_BASE}/api/attention?include_demo=${includeDemo ? "true" : "false"}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch attention items: ${res.statusText}`);
  return res.json();
}

export async function assignAttentionItem(
  id: string,
  applicationId: string,
  newStatus: string,
  note?: string
): Promise<{ success: boolean; application_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/api/attention/${id}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ application_id: applicationId, new_status: newStatus, note: note || "" }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to assign attention item: ${res.statusText}`);
  }
  return res.json();
}

export async function createAppFromAttention(
  id: string,
  data: { company_name: string; role_title: string; status?: string; note?: string }
): Promise<{ success: boolean; application_id: string }> {
  const res = await fetch(`${API_BASE}/api/attention/${id}/create-application`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to create application from triage: ${res.statusText}`);
  }
  return res.json();
}

export async function dismissAttentionItem(id: string): Promise<{ success: boolean; dismissed_id: string }> {
  const res = await fetch(`${API_BASE}/api/attention/${id}/dismiss`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to dismiss attention item: ${res.statusText}`);
  }
  return res.json();
}

export async function seedDemoAttention(): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/api/attention/seed-demo`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to seed demo attention: ${res.statusText}`);
  return res.json();
}

export async function clearDemoAttention(): Promise<{ success: boolean; deleted: number }> {
  const res = await fetch(`${API_BASE}/api/attention/clear-demo`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to clear demo attention: ${res.statusText}`);
  return res.json();
}





