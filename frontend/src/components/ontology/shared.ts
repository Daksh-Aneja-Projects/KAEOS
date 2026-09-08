import { ApiError } from '../../api/client';

/**
 * Shared bits for the Object Explorer's schema-authoring panels (Value
 * Types, Interfaces, Link Types, Object Sets) and the object-detail edit
 * additions in ObjectExplorer.tsx itself - split out here so neither file
 * duplicates the other's mutation-error handling. Kept in a plain .ts
 * module (no JSX) so this file only ever exports values, not components -
 * see InlineFeedback.tsx for the one component half of this split.
 */

/** The ontology's base_type closed set, mirrored exactly from the backend's
 * kaeos_enterprise.ontology.metamodel.BASE_TYPES - never a guessed list. */
export const BASE_TYPES = ['string', 'integer', 'float', 'boolean', 'timestamp', 'geopoint', 'array', 'json'];

export const FIELD_CLASS = 'w-full px-3 py-2 rounded-lg text-[13px] outline-none';

/**
 * 402/403 on a mutation is a governance notice (capability not enabled, or
 * this principal's role is too low for a console-gated write), never a red
 * error - the same contract `useEnterprisePanel` applies to reads, extended
 * here to every new ontology write (create value/interface/link type,
 * verify-conformance, object sets, dataset transactions).
 */
export function mutationTone(e: unknown): { notice: boolean; message: string } {
  return {
    notice: e instanceof ApiError && (e.status === 402 || e.status === 403),
    message: (e as { message?: string } | null)?.message || 'The request failed.',
  };
}
