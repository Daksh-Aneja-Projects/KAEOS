import { request } from '../http';

/* ─── Response shapes (bound to app/support/api/v1/router.py) ───
 * client.ts already merges the original wrappers (tickets/KB/CSAT/SLA/agent
 * actions - see api/endpoints/departments.ts) into the shared `api` object.
 * These are the newer reads/actions added on top; call `supportApi.*`
 * directly from the view rather than through `api`. */

export interface SupportTeamRow {
  id: string;
  name: string;
  description: string | null;
  tier: number;
  agent_count: number;
}

export interface SupportChannelRow {
  id: string;
  name: string;
  type: string;              // EMAIL | CHAT | PHONE | PORTAL
  routing_team: string | null;
  is_active: boolean;
}

export interface AgentLeaderboardRow {
  id: string;
  name: string;
  team: string | null;
  is_ai: boolean;
  avg_csat: number | null;   // null = no completed surveys yet, never fabricated
  survey_count: number;
  ticket_count: number;
}

export interface TicketCommentRow {
  id: string;
  author_type: string;       // CUSTOMER | AGENT | SYSTEM
  author: string;            // resolved display name, never a raw id/code
  body: string;
  is_internal: boolean;
  created_at: string | null;
}

export interface TicketTagRow { id: string; tag: string; }

export interface EscalationRuleRow {
  id: string;
  name: string;
  trigger: string;
  escalate_to_team: string | null;
  escalate_to_agent: string | null;
  time_threshold_mins: number;
  is_active: boolean;
}

export interface EscalationEventRow {
  id: string;
  ticket_id: string;
  ticket_number: string | null;
  ticket_subject: string | null;
  rule: string | null;
  from_agent: string | null;
  to_agent: string | null;
  reason: string | null;
  created_at: string | null;
}

export interface NPSSurveyRow {
  id: string;
  customer: string;
  score: number;
  feedback_text: string | null;
  created_at: string | null;
}

export interface FeedbackThemeRow {
  id: string;
  theme: string;
  volume_pct: number | null;
  severity: string;
}

export interface ArticleFeedbackRow {
  id: string;
  is_helpful: boolean;
  comment: string | null;
  created_at: string | null;
}

export const supportApi = {
  getSupportTeams: () => request<SupportTeamRow[]>('/support/teams'),
  getSupportChannels: () => request<SupportChannelRow[]>('/support/channels'),
  getSupportAgentLeaderboard: () => request<AgentLeaderboardRow[]>('/support/agents/leaderboard'),

  getTicketComments: (ticketId: string) =>
    request<TicketCommentRow[]>(`/support/tickets/${ticketId}/comments`),
  getTicketTags: (ticketId: string) =>
    request<TicketTagRow[]>(`/support/tickets/${ticketId}/tags`),

  publishKBArticle: (articleId: string) =>
    request<{ id: string; status: string }>(`/support/kb/articles/${articleId}/publish`, { method: 'PATCH' }),
  unpublishKBArticle: (articleId: string) =>
    request<{ id: string; status: string }>(`/support/kb/articles/${articleId}/unpublish`, { method: 'PATCH' }),
  getKBArticleFeedback: (articleId: string) =>
    request<ArticleFeedbackRow[]>(`/support/kb/articles/${articleId}/feedback`),

  getNPSSurveys: () => request<NPSSurveyRow[]>('/support/nps/surveys'),
  getFeedbackThemes: () => request<FeedbackThemeRow[]>('/support/feedback/themes'),

  getEscalationRules: () => request<EscalationRuleRow[]>('/support/escalation-rules'),
  getEscalationEvents: () => request<EscalationEventRow[]>('/support/escalation-events'),
};
