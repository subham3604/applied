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



