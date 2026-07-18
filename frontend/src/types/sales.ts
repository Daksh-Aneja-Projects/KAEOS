export interface SalesRep {
  id: string;
  name: string;
  email: string;
  team_id?: string;
  quota_ytd: number;
  attainment_ytd: number;
  is_active: boolean;
}

export interface Lead {
  id: string;
  company: string;
  contact_name: string;
  email: string;
  source: string;
  converted: boolean;
  score?: number;
}

export interface Account {
  id: string;
  name: string;
  industry?: string;
  arr: number;
  health: number;
}

export interface Opportunity {
  id: string;
  name: string;
  amount: number;
  stage: 'PROSPECTING' | 'QUALIFICATION' | 'PROPOSAL' | 'NEGOTIATION' | 'CLOSED_WON' | 'CLOSED_LOST';
  win_prob?: number;
  next_step?: string;
}

export interface SalesForecast {
  id: string;
  quarter: string;
  quota: number;
  commit: number;
  best_case: number;
  ai_forecast: number;
}
