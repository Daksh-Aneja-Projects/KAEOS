/**
 * KAEOS - Realtime Service
 * 
 * The Brain's nervous system - manages live data streams for
 * pages that need to stay synchronized with the cognitive loop.
 * 
 * Currently uses polling. Architecture supports upgrade to
 * WebSocket/SSE without changing consuming components.
 * 
 * Live streams:
 * - OODA Loop events (the cognitive heartbeat)
 * - Signals (external intelligence feed)
 * - Activity Feed (agent consciousness stream)
 * - Debate Engine (active deliberations)
 */

import { api } from '../api/client';
import type { OODAEventsResponse, CockpitData } from '../types';

/** Default polling intervals by stream type */
export const STREAM_INTERVALS = {
  /** OODA is the cognitive heartbeat - highest frequency */
  OODA: 15000,
  /** Signals are external intel - moderate frequency */
  SIGNALS: 30000,
  /** Activity feed - moderate frequency */
  ACTIVITY: 20000,
  /** Cockpit is executive view - lower frequency */
  COCKPIT: 60000,
  /** Debates - only when active */
  DEBATES: 30000,
} as const;

export const RealtimeService = {
  /**
   * Query the OODA cognitive loop - the Brain's heartbeat.
   * Returns observe/orient/decide/act events from the execution engine.
   */
  getOODAEvents: (): Promise<OODAEventsResponse> =>
    api.getOODAEvents(),

  /**
   * Query the Executive Cockpit - aggregated intelligence for C-suite.
   * Returns pioneer alerts, debate queue, org readiness, cost data.
   */
  getCockpit: (): Promise<CockpitData> =>
    api.getCockpit(),

  /**
   * Get the activity feed - the Brain's consciousness stream.
   */
  getActivityFeed: (limit: number = 50) =>
    api.getActivityFeed(limit),

  /**
   * Get raw signals - external intelligence before processing.
   */
  getSignals: () => api.getSignals(),

  /**
   * Get active debates - the Brain's current deliberations.
   */
  getActiveDebates: () => api.getRecentDebates(),
};
