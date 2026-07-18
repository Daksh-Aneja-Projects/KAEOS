/**
 * KAEOS - Brain Service
 * 
 * High-level cognitive service for the Enterprise Brain.
 * This isn't a REST wrapper - it's the semantic interface
 * between the Experience Layer and the Brain's intelligence.
 * 
 * Aggregates related API calls into meaningful operations:
 * - getBrainState() → full cognitive snapshot
 * - getDepartmentIntelligence() → domain-specific knowledge
 */

import { api } from '../api/client';
import type {
  BrainOverview, Department, DepartmentCapabilitiesResponse,
  Process, ProcessListResponse, WorkforceAgent, WorkforceListResponse,
} from '../types';

export const BrainService = {
  /**
   * Get the Enterprise Brain's current state - the single source of truth
   * for the overview page. Never returns mock data.
   */
  getOverview: (): Promise<BrainOverview> =>
    api.getBrainOverview(),

  /**
   * List all departments the Brain has learned about.
   * Returns whatever domains exist in the knowledge base.
   * If no rules exist, returns [].
   */
  getDepartments: (): Promise<{ total: number; departments: Department[] }> =>
    api.getDepartments(),

  /**
   * Get capabilities (skills) the Brain has for a specific department.
   */
  getDepartmentCapabilities: (deptId: string): Promise<DepartmentCapabilitiesResponse> =>
    api.getDepartmentCapabilities(deptId),

  /**
   * List all processes (workflows) the Brain manages.
   */
  getProcesses: (): Promise<ProcessListResponse> =>
    api.getProcesses(),

  /**
   * List all workforce agents - the Brain's deployed workforce.
   */
  getWorkforces: (): Promise<WorkforceListResponse> =>
    api.getWorkforces(),

  /**
   * Full cognitive snapshot - overview + departments in one call.
   * Used by pages that need the big picture.
   */
  getCognitiveSnapshot: async () => {
    const [overview, departments] = await Promise.allSettled([
      api.getBrainOverview(),
      api.getDepartments(),
    ]);
    return {
      overview: overview.status === 'fulfilled' ? overview.value : null,
      departments: departments.status === 'fulfilled' ? departments.value : null,
    };
  },
};
