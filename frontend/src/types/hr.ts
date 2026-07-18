/**
 * KAEOS - HR / Workforce Types
 * Response DTOs for HR domain endpoints
 */

export interface HREmployee {
  id: string;
  first_name: string;
  last_name: string;
  email?: string;
  status: string;
  job_title?: string;
  location?: string;
  hire_date?: string;
}

export interface HRRequisition {
  id: string;
  title: string;
  department?: string;
  status: string;
  headcount?: number;
  target_salary_min?: number;
  target_salary_max?: number;
}

export interface HRCandidate {
  id: string;
  name: string;
  stage: string;
  ai_score: number | null;
  requisition_id?: string;
}

export interface HRTimeOffRequest {
  id: string;
  employee_id: string;
  status: string;
  leave_type: string;
  start_date?: string;
  end_date?: string;
  hours_requested?: number;
}

export interface HRPerformanceReview {
  id: string;
  employee_id: string;
  status: string;
  manager_rating: number | null;
  self_rating?: number | null;
  cycle_id?: string;
}
