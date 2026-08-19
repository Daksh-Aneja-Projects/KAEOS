/**
 * KAEOS - Realtime stream cadences.
 *
 * The Brain's nervous system polls rather than pushes; these are the
 * per-stream intervals the live pages share so the cognitive loop, the
 * cockpit and the signal feeds stay on one agreed heartbeat.
 */

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
