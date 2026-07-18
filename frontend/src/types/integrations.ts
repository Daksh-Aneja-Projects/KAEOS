/**
 * KAEOS - Integration Types
 * Response DTOs for connectors, signals, candidates
 */

export interface ConnectorItem {
  id: string;
  name: string;
  category: string;
  connector_type: string;
  status: string;
  icon: string;
  description: string;
  auth_method: string;
  sync_frequency: string;
  last_sync_at: string | null;
  events_ingested: number;
  signals_extracted: number;
  error_count: number;
  avg_latency_ms: number;
  pii_scrub_enabled: boolean;
  pii_entities_found: number;
  connected_at: string | null;
}

export interface ConnectorsResponse {
  connectors: ConnectorItem[];
  stats: {
    total: number;
    connected: number;
    available: number;
    total_events_ingested: number;
    total_signals_extracted: number;
  };
}

export interface Signal {
  id: string;
  source_type: string;
  source_entity: string;
  signal_type: string;
  domain: string;
  clean_payload: string;
  authority_score: number;
  novelty_score: number;
  pii_present: boolean;
  created_at: string;
}

export interface CandidateRule {
  id: string;
  statement: string;
  trigger_json: any;
  action_json: any;
  domain: string;
  confidence_basis: string;
}
