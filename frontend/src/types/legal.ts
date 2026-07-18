export interface LegalTeamMember {
  id: string;
  name: string;
  role: string;
  email: string;
  bar_license_number?: string;
  is_active: boolean;
}

export interface LegalMatter {
  id: string;
  title: string;
  type: string;
  status: 'NEW' | 'IN_PROGRESS' | 'ON_HOLD' | 'RESOLVED' | 'CLOSED';
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  exposure?: string;
}

export interface Contract {
  id: string;
  title: string;
  counterparty: string;
  status: 'DRAFT' | 'IN_REVIEW' | 'APPROVED' | 'SIGNED' | 'ACTIVE' | 'EXPIRED' | 'TERMINATED';
  value: number;
  risk_score: number;
  expiry?: string;
}

export interface ContractClause {
  id: string;
  type: string;
  text: string;
  risk: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH';
  analysis?: string;
}

export interface ComplianceObligation {
  id: string;
  title: string;
  description?: string;
  status: 'PENDING' | 'COMPLETED' | 'OVERDUE' | 'WAIVED';
  owner?: string;
  due_date?: string;
}

export interface Case {
  id: string;
  name: string;
  stage: 'PLEADING' | 'DISCOVERY' | 'MOTION' | 'TRIAL' | 'APPEAL' | 'SETTLED' | 'DISMISSED';
  exposure: number;
  opposing_party: string;
  court?: string;
}

export interface DataSubjectRequest {
  id: string;
  name: string;
  email: string;
  type: 'ACCESS' | 'DELETE' | 'RECTIFY' | 'PORTABILITY' | 'RESTRICT';
  status: 'RECEIVED' | 'IDENTITY_VERIFIED' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  deadline: string;
}

export interface Patent {
  id: string;
  title: string;
  number?: string;
  status: 'PENDING' | 'ACTIVE' | 'ABANDONED' | 'EXPIRED';
  filing_date?: string;
  jurisdiction: string;
}
