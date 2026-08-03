/**
 * KAEOS - API Client (barrel).
 * Transport lives in ./http, response types in ./types, and the endpoint
 * catalog is split by domain under ./endpoints. This file re-exports all of
 * it and assembles the single `api` object, so every existing
 * `import { api, request, SomeType } from '../api/client'` keeps resolving.
 */
export * from './http';
export * from './types';

import { governanceApi } from './endpoints/governance';
import { enterpriseApi } from './endpoints/enterprise';
import { departmentsApi } from './endpoints/departments';
import { operationsApi } from './endpoints/operations';

export const api = {
  ...governanceApi,
  ...enterpriseApi,
  ...departmentsApi,
  ...operationsApi,
};
