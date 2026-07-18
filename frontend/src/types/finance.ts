export interface ChartOfAccount {
  id: string;
  code: string;
  name: string;
  type: 'ASSET' | 'LIABILITY' | 'EQUITY' | 'REVENUE' | 'EXPENSE';
  balance: number;
  currency: string;
  is_active: boolean;
  department?: string;
  cost_center?: string;
}

export interface Vendor {
  id: string;
  code: string;
  name: string;
  status: 'ACTIVE' | 'INACTIVE' | 'ON_HOLD';
  payment_terms: number;
  spend_ytd: number;
  performance_score: number;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
}

export interface Invoice {
  id: string;
  number: string;
  vendor_id: string;
  status: 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'PAID' | 'VOIDED' | 'OVERDUE';
  total: number;
  balance: number;
  due_date: string;
  po_number?: string;
  three_way_match: 'MATCHED' | 'MISMATCHED' | 'PENDING_RECEIPT' | 'NOT_APPLICABLE';
  ai_duplicate: boolean;
}

export interface Customer {
  id: string;
  code: string;
  name: string;
  status: 'ACTIVE' | 'INACTIVE' | 'CREDIT_HOLD';
  outstanding: number;
  revenue_ytd: number;
  dso: number;
  churn_risk: number;
  aging: {
    current: number;
    '30': number;
    '60': number;
    '90': number;
    over_90: number;
  };
}

export interface CustomerInvoice {
  id: string;
  number: string;
  customer_id: string;
  status: 'DRAFT' | 'SENT' | 'PAID' | 'OVERDUE' | 'PARTIALLY_PAID';
  total: number;
  balance: number;
  due_date: string;
  dunning_level: number;
}

export interface Budget {
  id: string;
  name: string;
  type: string;
  year: number;
  status: 'DRAFT' | 'ACTIVE' | 'CLOSED';
  planned: number;
  actual: number;
  variance: number;
  variance_pct: number;
  department: string;
}

export interface BudgetLine {
  id: string;
  category: string;
  period: number;
  label: string;
  planned: number;
  actual: number;
  committed: number;
  variance: number;
}

export interface ExpenseReport {
  id: string;
  number: string;
  title: string;
  employee_id: string;
  status: 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'REIMBURSED';
  total: number;
  approved: number;
  compliance_score: number;
  violations: string[];
}

export interface BankAccount {
  id: string;
  name: string;
  bank: string;
  masked_number: string;
  classification: 'OPERATING' | 'SAVINGS' | 'INVESTMENT' | 'ESCROW';
  balance: number;
  available: number;
  currency: string;
  last_reconciled?: string;
}

export interface AuditFinding {
  id: string;
  number: string;
  title: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: 'OPEN' | 'IN_PROGRESS' | 'REMEDIATED' | 'CLOSED';
  area: string;
  impact: number;
  owner: string;
  ai_detected: boolean;
}

export interface SOXControl {
  id: string;
  code: string;
  name: string;
  type: string;
  frequency: string;
  nature: string;
  area: string;
  status: 'EFFECTIVE' | 'DEFICIENT' | 'REMEDIED';
  risk_level: string;
  ai_score: number;
}
