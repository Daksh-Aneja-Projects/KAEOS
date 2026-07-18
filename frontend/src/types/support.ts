export interface SupportTeam {
  id: string;
  name: string;
  tier: number;
}

export interface SupportAgent {
  id: string;
  name: string;
  email: string;
  team_id?: string;
  is_ai: boolean;
  is_active: boolean;
}

export interface Ticket {
  id: string;
  number: string;
  subject: string;
  status: 'NEW' | 'ASSIGNED' | 'OPEN' | 'PENDING_CUSTOMER' | 'RESOLVED' | 'CLOSED';
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT';
  created_at: string;
}

export interface KBArticle {
  id: string;
  title: string;
  views: number;
  published: boolean;
  helpfulness: number;
}

export interface CSATSurvey {
  id: string;
  ticket_id: string;
  rating: number;
  comment?: string;
  sentiment?: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE';
}

export interface SLAMetric {
  id: string;
  date: string;
  total: number;
  breached: number;
  compliance: number;
}
