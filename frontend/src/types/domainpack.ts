/**
 * KAEOS - Domain Pack Types
 * Type definitions for domain pack marketplace and installation tracking.
 * Maps to backend workforce/models/domain_pack.py
 */

export type DomainPackSource = 'BUILT_IN' | 'MARKETPLACE' | 'CUSTOM';

export interface DomainPack {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  long_description?: string | null;
  version: string;
  icon: string;
  category: string;
  source: DomainPackSource;
  author: string;
  required_integrations: { category: string; examples: string[]; data_provided: string[] }[];
  optional_integrations: { category: string; examples: string[]; data_provided: string[] }[];
  capabilities: {
    id: string;
    name: string;
    description: string;
    processes?: string[];
    agents?: string[];
    compliance?: string[];
  }[];
  agent_definitions?: {
    name: string;
    type: string;
    capability: string;
    description: string;
    skills: string[];
    persona?: string;
  }[];
  process_definitions?: {
    id: string;
    name: string;
    capability: string;
    steps: any[];
    sla_hours: number;
  }[];
  knowledge_templates?: string[];
  deployment_config?: Record<string, any>;
  compliance_frameworks: string[];
  install_count?: number;
  rating?: number;
  rating_count?: number;
  status: string;
  created_at: string | null;
  updated_at?: string | null;
}

export interface DomainPackInstallation {
  id: string;
  domain_pack_id: string;
  installed_version: string;
  status: string;
  customizations: Record<string, any>;
  installed_at: string | null;
}
