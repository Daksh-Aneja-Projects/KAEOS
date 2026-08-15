import { request } from '../http';

/* ─── Response shapes (bound to app/legal/api/v1/router.py) ─── */

export interface ContractTemplateRow {
  id: string;
  name: string;
  contract_type: string;
  version: string;
  is_active: boolean;
}

export interface RegulatoryRequirementRow {
  id: string;
  regulation: string;
  section: string;
  title: string;
  description: string | null;
  jurisdiction: string;
}

export interface ComplianceAssessmentRow {
  id: string;
  framework: string;
  assessment_date: string;
  assessor: string;
  score: number | null;
  findings_count: number;
}

export interface CaseEventRow {
  id: string;
  title: string;
  date: string;
  description: string | null;
  is_milestone: boolean;
}

export interface CourtFilingRow {
  id: string;
  document_name: string;
  filing_date: string;
  filed_by: string | null;
}

export interface TrademarkRow {
  id: string;
  mark_name: string;
  registration_number: string | null;
  status: string;
  class_code: string | null;
  jurisdiction: string;
  renewal_date: string | null;
}

export interface TradeSecretRow {
  id: string;
  asset_name: string;
  description: string | null;
  custodian: string | null;
  security_level: string;
}

export interface PIARow {
  id: string;
  system_name: string;
  pii_elements: string | null;
  risk_rating: string;
  remediation_required: boolean;
  status: string;
  signoff_date: string | null;
}

export interface ROPARow {
  id: string;
  data_controller: string;
  purpose: string;
  subjects: string | null;
  recipients: string | null;
  retention_period: string | null;
}

export interface LegalTeamMemberRow {
  id: string;
  name: string;
  role: string;
  email: string;
  bar_license_number: string | null;
  is_active: boolean;
}

export const legalApi = {
  getLegalContractTemplates: () => request<ContractTemplateRow[]>('/legal/contract-templates'),
  getLegalComplianceRequirements: () => request<RegulatoryRequirementRow[]>('/legal/compliance/requirements'),
  getLegalComplianceAssessments: () => request<ComplianceAssessmentRow[]>('/legal/compliance/assessments'),
  getLegalCaseEvents: (caseId: string) => request<CaseEventRow[]>(`/legal/cases/${caseId}/events`),
  getLegalCaseFilings: (caseId: string) => request<CourtFilingRow[]>(`/legal/cases/${caseId}/filings`),
  getLegalTrademarks: () => request<TrademarkRow[]>('/legal/ip/trademarks'),
  getLegalTradeSecrets: () => request<TradeSecretRow[]>('/legal/ip/trade-secrets'),
  getLegalPias: () => request<PIARow[]>('/legal/privacy/pias'),
  getLegalRopa: () => request<ROPARow[]>('/legal/privacy/ropa'),
  getLegalTeam: () => request<LegalTeamMemberRow[]>('/legal/team'),
};
