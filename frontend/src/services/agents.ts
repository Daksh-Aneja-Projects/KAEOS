/**
 * KAEOS - Agent Service
 * 
 * Service layer for the Agent Factory - the Brain's ability
 * to create, compile, deploy, and govern autonomous agents.
 * 
 * This isn't CRUD on agents. This is lifecycle management
 * for cognitive entities that make decisions.
 */

import { api } from '../api/client';

export const AgentService = {
  // ── Blueprint Lifecycle ──
  create: (prompt: string, createdBy?: string) =>
    api.createBlueprint(prompt, createdBy),

  listBlueprints: () => api.listBlueprints(),
  getBlueprint: (id: string) => api.getBlueprint(id),

  refine: (id: string, edits: any) =>
    api.refineBlueprint(id, edits),

  approve: (id: string, approvedBy?: string) =>
    api.approveBlueprint(id, approvedBy),

  compile: (id: string) => api.compileBlueprint(id),

  deploy: (id: string, triggerConfig?: any) =>
    api.deployBlueprint(id, triggerConfig),

  // ── Deployed Agent Operations ──
  listDeployed: () => api.listDeployedAgents(),
  getAgent: (id: string) => api.getDeployedAgent(id),
  stop: (id: string) => api.stopAgent(id),
  pause: (id: string) => api.pauseAgent(id),

  // ── Debate Engine - the Brain's deliberation system ──
  getRecentDebates: () => api.getRecentDebates(),
  getDebateTranscript: (executionId: string) =>
    api.getDebateTranscript(executionId),

  // ── Fairness - the Brain's ethical governor ──
  getFairnessLog: (limit: number = 50) =>
    api.getFairnessLog(limit),

  overrideFairness: (logId: string, overrideBy: string, justification: string) =>
    api.overrideFairness(logId, overrideBy, justification),

  // ── Activity Feed - the Brain's consciousness stream ──
  getFeed: (limit: number = 50, unreadOnly: boolean = false) =>
    api.getActivityFeed(limit, unreadOnly),

  markRead: (eventIds: string[]) =>
    api.markFeedRead(eventIds),

  getActionRequired: () => api.getActionRequired(),

  // ── HITL - Human-in-the-Loop checkpoints ──
  getPendingHITL: () => api.getPendingHITL(),
  approveHITL: (execId: string) => api.approveHITL(execId),
  rejectHITL: (execId: string) => api.rejectHITL(execId),
};
