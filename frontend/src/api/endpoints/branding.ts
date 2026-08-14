import { request } from '../http';

/**
 * White-label tenant theming. GET is available to any authed tenant user (so the
 * SPA can theme itself on load); PUT is admin-only and re-validated server-side
 * (hex colors, http(s) logo URL). See backend app/api/routes/branding.py.
 */

export interface Branding {
  product_name: string;
  primary_color: string;
  accent_color: string;
  logo_url: string | null;
  login_subtitle: string | null;
  /** true when the tenant has never set a brand (KAEOS defaults returned). */
  is_default: boolean;
}

export type BrandingInput = Omit<Branding, 'is_default'>;

export const brandingApi = {
  getBranding: () => request<Branding>('/branding'),
  updateBranding: (b: BrandingInput) =>
    request<Branding>('/branding', { method: 'PUT', body: JSON.stringify(b) }),
};
