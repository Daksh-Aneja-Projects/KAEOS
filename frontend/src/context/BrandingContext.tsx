import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { api, type Branding } from '../api/client';

/**
 * White-label branding, applied app-wide.
 *
 * Fetches the tenant brand once a session exists (mounted inside the authed
 * shell, so it never fires an unauthenticated /branding call that http's
 * 401-handler would turn into a reload loop). When a tenant has set a custom
 * brand it overrides the primary color as a CSS variable on :root — Tailwind v4
 * derives every `.bg-primary` / `.text-primary` / focus-ring from
 * `--color-primary`, so one override recolors the app chrome. An untouched
 * tenant (is_default) leaves the shipped design pixel-identical.
 *
 * `product_name` is exposed so the shell renders the tenant's name where it
 * would otherwise hardcode "KAEOS".
 */

const KAEOS_DEFAULT: Branding = {
  product_name: 'KAEOS',
  primary_color: '#5e6ad2',
  accent_color: '#22d3ee',
  logo_url: null,
  login_subtitle: null,
  is_default: true,
};

interface BrandingContextType {
  brand: Branding;
  /** Re-fetch and re-apply after an admin saves the brand. */
  reloadBranding: () => Promise<void>;
  /** Apply an in-progress brand (live preview) without persisting. */
  applyPreview: (b: Branding) => void;
}

const BrandingContext = createContext<BrandingContextType>({
  brand: KAEOS_DEFAULT,
  reloadBranding: async () => {},
  applyPreview: () => {},
});

export const useBranding = () => useContext(BrandingContext);

function applyBrand(b: Branding) {
  const root = document.documentElement;
  if (b.is_default) {
    // Nothing customized — hand the CSS back to the shipped @theme defaults.
    root.style.removeProperty('--color-primary');
    root.style.removeProperty('--color-primary-hover');
    root.style.removeProperty('--brand-accent');
  } else {
    root.style.setProperty('--color-primary', b.primary_color);
    root.style.setProperty('--color-primary-hover', b.primary_color);
    root.style.setProperty('--brand-accent', b.accent_color);
  }
}

export const BrandingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [brand, setBrand] = useState<Branding>(KAEOS_DEFAULT);

  const reloadBranding = useCallback(async () => {
    try {
      const b = await api.getBranding();
      setBrand(b);
      applyBrand(b);
    } catch {
      // A branding read failure must never blank the app; keep KAEOS defaults.
      setBrand(KAEOS_DEFAULT);
      applyBrand(KAEOS_DEFAULT);
    }
  }, []);

  const applyPreview = useCallback((b: Branding) => {
    setBrand(b);
    applyBrand(b);
  }, []);

  useEffect(() => { void reloadBranding(); }, [reloadBranding]);

  const value = useMemo(() => ({ brand, reloadBranding, applyPreview }),
    [brand, reloadBranding, applyPreview]);

  return (
    <BrandingContext.Provider value={value}>
      {children}
    </BrandingContext.Provider>
  );
};
