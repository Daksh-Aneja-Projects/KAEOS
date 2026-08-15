import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Users, Landmark, Target, Building2, Wallet, ShieldCheck, HeartPulse, Banknote } from 'lucide-react';
import DomainIcon from './DomainIcon';

/**
 * Resolution is asserted by comparing the rendered SVG markup of the tile's
 * icon against the same lucide icon rendered directly. This keeps the tests
 * independent of lucide's class-naming scheme across versions.
 */
function iconMarkup(node: React.ReactElement): string {
  const { container } = render(node);
  return container.querySelector('svg')!.innerHTML;
}

function tileSvg(props: React.ComponentProps<typeof DomainIcon>) {
  const { container } = render(<DomainIcon {...props} />);
  return container.querySelector('svg')!;
}

describe('DomainIcon', () => {
  it('resolves a department slug to its icon', () => {
    expect(tileSvg({ hint: 'hr' }).innerHTML).toBe(iconMarkup(<Users />));
    expect(tileSvg({ hint: 'finance' }).innerHTML).toBe(iconMarkup(<Landmark />));
  });

  it('is case-insensitive on slugs', () => {
    expect(tileSvg({ hint: 'Finance' }).innerHTML).toBe(iconMarkup(<Landmark />));
  });

  it('resolves healthcare and lending to their own distinct icon and color', () => {
    expect(tileSvg({ hint: 'healthcare' }).innerHTML).toBe(iconMarkup(<HeartPulse />));
    expect(tileSvg({ hint: 'lending' }).innerHTML).toBe(iconMarkup(<Banknote />));
    // Full department names (as returned by the API), not just the slug.
    expect(tileSvg({ hint: 'Healthcare' }).innerHTML).toBe(iconMarkup(<HeartPulse />));
    expect(tileSvg({ hint: 'Lending & Credit' }).innerHTML).toBe(iconMarkup(<Banknote />));
    // Neither collides with the generic fallback or with each other.
    const healthcareTile = render(<DomainIcon hint="healthcare" />).container.firstElementChild as HTMLElement;
    const lendingTile = render(<DomainIcon hint="lending" />).container.firstElementChild as HTMLElement;
    const fallbackTile = render(<DomainIcon hint="zzz-unknown" />).container.firstElementChild as HTMLElement;
    expect(healthcareTile.style.background).not.toBe(lendingTile.style.background);
    expect(healthcareTile.style.background).not.toBe(fallbackTile.style.background);
    expect(lendingTile.style.background).not.toBe(fallbackTile.style.background);
  });

  it('resolves a legacy emoji to the replacement icon', () => {
    expect(tileSvg({ hint: '\u{1F465}' }).innerHTML).toBe(iconMarkup(<Users />));
    expect(tileSvg({ hint: '\u{1F6E1}️' }).innerHTML).toBe(iconMarkup(<ShieldCheck />));
  });

  it('resolves free-text names via keyword matching', () => {
    expect(tileSvg({ hint: 'Recruiting and Talent Acquisition' }).innerHTML)
      .toBe(iconMarkup(<Target />));
    expect(tileSvg({ hint: 'Payroll Processing' }).innerHTML).toBe(iconMarkup(<Wallet />));
    expect(tileSvg({ hint: 'Human Resources' }).innerHTML).toBe(iconMarkup(<Users />));
  });

  it('falls back to the generic building for unknown hints', () => {
    expect(tileSvg({ hint: 'zzz-completely-unknown' }).innerHTML)
      .toBe(iconMarkup(<Building2 />));
    expect(tileSvg({}).innerHTML).toBe(iconMarkup(<Building2 />));
  });

  it('uses fallbackHint when the primary hint does not resolve', () => {
    expect(tileSvg({ hint: '\u{1F937}', fallbackHint: 'finance' }).innerHTML)
      .toBe(iconMarkup(<Landmark />));
  });

  it('prefers the primary hint over fallbackHint when both resolve', () => {
    expect(tileSvg({ hint: 'hr', fallbackHint: 'finance' }).innerHTML)
      .toBe(iconMarkup(<Users />));
  });

  it('sizes the tile and scales the glyph to half the tile', () => {
    const { container } = render(<DomainIcon hint="hr" size={56} />);
    const tile = container.firstElementChild as HTMLElement;
    expect(tile.style.width).toBe('56px');
    expect(tile.style.height).toBe('56px');
    const svg = container.querySelector('svg') as SVGElement;
    expect(svg.style.width).toBe('28px');
    expect(svg.style.height).toBe('28px');
  });

  it('defaults to a 40px tile', () => {
    const { container } = render(<DomainIcon hint="hr" />);
    const tile = container.firstElementChild as HTMLElement;
    expect(tile.style.width).toBe('40px');
  });
});
