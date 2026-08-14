import { request } from '../http';

/* ─── Response shapes (bound to app/healthcare/api/v1/router.py) ─── */

export interface HealthcareDashboard {
  total_encounters: number;
  open_encounters: number;
  phi_disclosures: number;
  active_consents: number;
  open_clinical_tasks: number;
}

export interface HealthcareEncounter {
  id: string;
  encounter_number: string;
  patient_ref: string;
  type: string;                 // office_visit | telehealth | inpatient
  status: string;               // OPEN | TRIAGED | CODED | CLOSED
  reason: string | null;
  priority: string | null;      // ROUTINE | URGENT | EMERGENT
  diagnosis_codes: string[];
}

export interface PHIDisclosureRow {
  id: string;
  purpose: string;              // payment | treatment | operations | marketing | research
  recipient: string;
  fields: string[];
  part2: boolean;               // touched 42 CFR Part 2 substance-use records
  authorized: boolean;          // always true on a persisted (gate-passed) row
  justification: string;        // minimum-necessary justification
  encounter_id: string | null;
}

export interface ConsentRow {
  id: string;
  patient_ref: string;
  scope: string;
  part2: boolean;
  active: boolean;
  granted_at: string | null;
  revoked_at: string | null;
}

export interface ClinicalTaskRow {
  id: string;
  type: string;                 // coding | prior_auth | ...
  status: string;               // OPEN | IN_PROGRESS | PENDING_HITL | DONE | BLOCKED
  assignee: string | null;
  encounter_id: string | null;
  detail: Record<string, any>;
}

const q = (status?: string) => (status ? `?status=${encodeURIComponent(status)}` : '');

export const healthcareApi = {
  getHealthcareDashboard: () => request<HealthcareDashboard>('/healthcare/dashboard'),
  // Same shared kpis/charts/insights shape DomainAnalytics renders.
  getHealthcareAnalytics: () => request<any>('/healthcare/analytics'),

  getHealthcareEncounters: (status?: string) =>
    request<HealthcareEncounter[]>(`/healthcare/encounters${q(status)}`),
  createHealthcareEncounter: (body: { patient_ref: string; encounter_type: string; reason?: string }) =>
    request<HealthcareEncounter>('/healthcare/encounters', { method: 'POST', body: JSON.stringify(body) }),

  getHealthcareDisclosures: () => request<PHIDisclosureRow[]>('/healthcare/disclosures'),
  // A disclosure that fails minimum-necessary / authorization / Part 2 is refused
  // (422) and never persisted; the caller surfaces the blocking reason.
  createHealthcareDisclosure: (body: Record<string, any>) =>
    request<any>('/healthcare/disclosures', { method: 'POST', body: JSON.stringify(body) }),

  getHealthcareConsent: () => request<ConsentRow[]>('/healthcare/consent'),
  createHealthcareConsent: (body: { patient_ref: string; scope: string; part2?: boolean }) =>
    request<ConsentRow>('/healthcare/consent', { method: 'POST', body: JSON.stringify(body) }),
  revokeHealthcareConsent: (id: string) =>
    request<{ id: string; active: boolean }>(`/healthcare/consent/${id}/revoke`, { method: 'POST' }),

  getHealthcareTasks: (status?: string) =>
    request<ClinicalTaskRow[]>(`/healthcare/tasks${q(status)}`),
  createHealthcareTask: (body: { task_type: string; encounter_id?: string; assignee?: string }) =>
    request<any>('/healthcare/tasks', { method: 'POST', body: JSON.stringify(body) }),
};
