/**
 * KAEOS - Configuration Types
 * Response DTOs for LLM routing, MCP tools, ontology, federated settings
 */

export interface LLMConfigItem {
  id?: string;
  layer: string;
  model_name: string;
  api_key: string;
  provider: string;
}

export interface MCPToolItem {
  id?: string;
  tool_id: string;
  is_active: boolean;
  rate_limit_per_hour: number;
  api_key?: string;
}

export interface OntologyConfigItem {
  id?: string;
  department: string;
  default_half_life_days: number;
}

export interface FederatedConfigItem {
  id?: string;
  department: string;
  opt_in: boolean;
}
