import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import BillingSettings from './BillingSettings';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getBillingEntitlements: vi.fn(),
    getBaselines: vi.fn(),
    createCheckoutSession: vi.fn(),
    createPortalSession: vi.fn(),
    putBaseline: vi.fn(),
  },
}));

const entitlements = (managed: boolean) => ({
  tenant_id: 'tenant_acme',
  plan: 'free',
  managed_cloud: managed,
  // Self-host grants everything; managed free grants nothing.
  features: { webhooks: !managed, sso: !managed, scim: !managed, advanced_connectors: !managed },
  usage: {
    tenant_id: 'tenant_acme', period_start: '2026-08-01', plan: 'free',
    metered_executions: 120, included_allowance: 500, overage_units: 0,
  },
  plans: {
    free: { features: [], allowance: 500 },
    oss: { features: [], allowance: 0 },
    team: { features: ['webhooks'], allowance: 5000 },
    business: { features: ['webhooks', 'sso', 'advanced_connectors'], allowance: 25000 },
    enterprise: { features: ['webhooks', 'sso', 'scim', 'advanced_connectors'], allowance: 100000 },
  },
  seats: null,
});

beforeEach(() => {
  vi.mocked(api.getBaselines).mockResolvedValue({ baselines: [] });
});

describe('BillingSettings', () => {
  it('shows the self-host note and no purchase buttons when managed_cloud=false', async () => {
    vi.mocked(api.getBillingEntitlements).mockResolvedValue(entitlements(false) as any);
    render(<BillingSettings />);
    expect(await screen.findByText(/Self-hosted: all platform features included/)).toBeInTheDocument();
    expect(screen.queryByText('Upgrade')).toBeNull();
    expect(screen.queryByText('Manage billing')).toBeNull();
  });

  it('shows upgrade and manage-billing buttons when managed_cloud=true', async () => {
    vi.mocked(api.getBillingEntitlements).mockResolvedValue(entitlements(true) as any);
    render(<BillingSettings />);
    expect(await screen.findByText('Manage billing')).toBeInTheDocument();
    // One Upgrade per paid tier that is not the current plan: team/business/enterprise.
    expect(screen.getAllByText('Upgrade')).toHaveLength(3);
    expect(screen.queryByText(/Self-hosted: all platform features included/)).toBeNull();
  });
});
