import { request } from '../http';

/* ─── Response shapes (bound to app/engineering/api/v1/router.py) ─── */

export interface OnCallRotationRow {
  id: string;
  engineer_id: string;
  engineer_name: string | null;
  squad: string;
  role: string;              // PRIMARY | SECONDARY
  active: boolean;
  starts_at: string | null;
  ends_at: string | null;
}

export interface PipelineRunRow {
  id: string;
  service_id: string | null;
  pull_request_id: string | null;
  pipeline_name: string;
  run_number: number;
  status: string;             // PENDING | RUNNING | SUCCEEDED | FAILED | CANCELED
  trigger: string | null;
  branch: string | null;
  commit_sha: string | null;
  tests_passed: number | null;
  tests_failed: number | null;
  duration_seconds: number | null;
  started_at: string | null;
  completed_at: string | null;
}

const q = (params: Record<string, string | boolean | undefined>) => {
  const parts = Object.entries(params).filter(([, v]) => v !== undefined && v !== '');
  return parts.length ? `?${parts.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')}` : '';
};

export const engineeringApi = {
  getOnCallRotations: (params?: { squad?: string; active_only?: boolean }) =>
    request<OnCallRotationRow[]>(`/engineering/oncall${q(params || {})}`),

  getPipelineRuns: (params?: { service_id?: string; status?: string }) =>
    request<PipelineRunRow[]>(`/engineering/pipeline-runs${q(params || {})}`),
};
