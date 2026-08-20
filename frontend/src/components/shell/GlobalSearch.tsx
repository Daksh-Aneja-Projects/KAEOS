import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { Search, X } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { api } from '../../api/client';
import { canSeeDepartment } from '../../lib/departments';
import { focusMenuItem } from './menuNav';

// Search results - navigable modules
const SEARCHABLE_MODULES = [
  { path: '/', label: 'Workforce Dashboard', keywords: 'home dashboard departments overview' },
  { path: '/departments', label: 'Departments', keywords: 'hr finance department workforce' },
  { path: '/deploy', label: 'Deploy Studio', keywords: 'deploy wizard department' },
  { path: '/marketplace', label: 'Marketplace', keywords: 'packs domain install' },
  { path: '/integrations', label: 'Integrations', keywords: 'connectors sync schema mapper' },
  { path: '/analytics', label: 'Analytics', keywords: 'roi metrics hours saved' },
  { path: '/departments/hr', label: 'HR Department', keywords: 'hr employees recruiting benefits payroll' },
  { path: '/departments/healthcare', label: 'Healthcare Department', keywords: 'healthcare clinical encounters phi disclosure consent hipaa part2 patient' },
  { path: '/departments/lending', label: 'Lending Department', keywords: 'lending loan credit underwriting ecoa fair-lending adverse action banking' },
  { path: '/departments/procurement', label: 'Procurement Department', keywords: 'procurement purchase order requisition vendor three-way match ofac sod spend' },
  { path: '/platform/knowledge', label: 'Knowledge', keywords: 'rules skills topology extraction connectors' },
  { path: '/platform/agents', label: 'Agents', keywords: 'deploy blueprint ooda llm mcp marketplace' },
  { path: '/platform/decisions', label: 'Decisions', keywords: 'cockpit compliance provenance redteam hitl fairness debates governance trust' },
  { path: '/platform/proving-ground', label: 'Proving Ground', keywords: 'assurance score gate catch-rate known-bad attack battery governance proof red team' },
  { path: '/platform/settings', label: 'Settings', keywords: 'config ontology federated' },
  { path: '/platform/users', label: 'User Management', keywords: 'admin roles users rbac' },
  { path: '/platform/foundry', label: 'AI Foundry', keywords: 'foundry training dataset fine-tune model evolution learning v2' },
  { path: '/platform/onboarding', label: 'Client Onboarding', keywords: 'onboard tenant client provision new customer setup' },
  { path: '/getting-started', label: 'Getting Started', keywords: 'getting started onboarding checklist activate setup first' },
];

/**
 * The header's global search box: module "Go to" matches plus Company Brain
 * entity search, with roving keyboard nav in the dropdown.
 *
 * Extracted from Shell (M7.3) so that per-keystroke state (query, focus,
 * entity results) re-renders only this component - previously every keystroke
 * re-rendered the entire route tree. The only prop is the stable `userDept`
 * primitive, so Shell renders never cascade here for unstable-prop reasons.
 */
export default function GlobalSearch({ userDept }: { userDept: string | null }) {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Cmd/Ctrl+K to focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === 'Escape') {
        searchRef.current?.blur();
        setSearchQuery('');
        setSearchFocused(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Scoped users don't get "Go to" entries for other departments' surfaces.
  const visibleModules = SEARCHABLE_MODULES.filter(m => {
    const deptMatch = m.path.match(/^\/departments\/([^/]+)/);
    return !deptMatch || canSeeDepartment(userDept, deptMatch[1]);
  });
  const searchResults = searchQuery.length >= 2
    ? visibleModules.filter(m =>
        m.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.keywords.includes(searchQuery.toLowerCase())
      )
    : [];

  // Entity search: the box only ever matched module NAMES, so searching
  // "invoice" surfaced the Accounts Payable page but never an actual invoice.
  // The Company Brain already exposes cross-entity search - use it.
  const [entityResults, setEntityResults] = useState<{ label: string; sub: string; path: string }[]>([]);
  useEffect(() => {
    if (searchQuery.length < 2) { setEntityResults([]); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await api.globalSearch(searchQuery);
        if (cancelled) return;
        const out: { label: string; sub: string; path: string }[] = [];
        (r?.results?.rules || []).slice(0, 4).forEach((x: any) =>
          out.push({ label: x.statement, sub: `Rule · ${x.domain ?? ''}`, path: '/platform/knowledge' }));
        (r?.results?.skills || []).slice(0, 4).forEach((x: any) =>
          out.push({ label: x.skill_id, sub: `Skill · ${x.domain ?? ''}`, path: '/platform/knowledge' }));
        (r?.results?.signals || []).slice(0, 3).forEach((x: any) =>
          out.push({ label: x.source, sub: `Signal · ${x.domain ?? ''}`, path: '/platform/knowledge' }));
        setEntityResults(out);
      } catch { if (!cancelled) setEntityResults([]); }
    }, 220);  // debounce: this hits the API on every keystroke otherwise
    return () => { cancelled = true; clearTimeout(t); };
  }, [searchQuery]);

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); focusMenuItem(e.currentTarget, 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusMenuItem(e.currentTarget, -1); }
    else if (e.key === 'Escape') { setSearchFocused(false); setSearchQuery(''); searchRef.current?.focus(); }
  };

  return (
    /* Fixed-width search would overflow a phone; it is keyboard-driven
       (⌘K) chrome, so it yields below md rather than shrinking. */
    <div className="relative hidden md:block" onKeyDown={handleSearchKeyDown}>
      <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
      <input
        ref={searchRef}
        type="text"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        onFocus={() => setSearchFocused(true)}
        onBlur={() => setTimeout(() => setSearchFocused(false), 200)}
        placeholder="Search… ⌘K"
        role="combobox"
        aria-expanded={searchFocused && (searchResults.length > 0 || entityResults.length > 0)}
        aria-controls="global-search-results"
        aria-autocomplete="list"
        className="pl-8 pr-3 py-1.5 rounded border text-[12px] focus:outline-none focus:ring-1 transition-all"
        style={{
          background: colors.canvas,
          borderColor: searchFocused ? colors.primary : colors.hairline,
          color: colors.ink,
          width: searchFocused ? '280px' : '200px',
        }}
      />
      {searchQuery && (
        <button type="button" aria-label="Clear search" onClick={() => setSearchQuery('')}
          className="absolute right-1 top-1/2 -translate-y-1/2 p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
          <X className="w-3 h-3" />
        </button>
      )}
      {/* Search Results Dropdown */}
      {searchFocused && (searchResults.length > 0 || entityResults.length > 0) && (
        <div id="global-search-results" role="listbox" aria-label="Search results"
          className="absolute top-full left-0 mt-1 w-full rounded border shadow-lg z-50 overflow-hidden max-h-[420px] overflow-y-auto"
          style={{ background: colors.surface1, borderColor: colors.hairline }}>
          {searchResults.length > 0 && (
            <div className="px-3 pt-2 pb-1 text-[11px] uppercase tracking-wider font-semibold"
              style={{ color: colors.inkSubtle }}>Go to</div>
          )}
          {searchResults.map(r => (
            <button key={r.path} type="button" role="option" data-menuitem
              onClick={() => { navigate(r.path); setSearchQuery(''); setSearchFocused(false); }}
              className="w-full text-left px-3 py-2 text-[13px] cursor-pointer hover:bg-surface2 transition-colors flex items-center gap-2 focus:outline-none focus-visible:bg-surface2"
              style={{ color: colors.ink }}>
              <Search className="w-3 h-3" style={{ color: colors.inkSubtle }} />
              {r.label}
            </button>
          ))}
          {entityResults.length > 0 && (
            <div className="px-3 pt-2 pb-1 text-[11px] uppercase tracking-wider font-semibold border-t"
              style={{ color: colors.inkSubtle, borderColor: colors.hairline }}>In your company brain</div>
          )}
          {entityResults.map((r, i) => (
            <button key={`${r.path}-${i}`} type="button" role="option" data-menuitem
              onClick={() => { navigate(r.path); setSearchQuery(''); setSearchFocused(false); }}
              className="w-full text-left px-3 py-2 cursor-pointer hover:bg-surface2 transition-colors block focus:outline-none focus-visible:bg-surface2"
              style={{ color: colors.ink }}>
              <div className="text-[12px] truncate">{r.label}</div>
              <div className="text-[11px]" style={{ color: colors.inkSubtle }}>{r.sub}</div>
            </button>
          ))}
        </div>
      )}
      {searchFocused && searchQuery.length >= 2 && searchResults.length === 0 && entityResults.length === 0 && (
        <div className="absolute top-full left-0 mt-1 w-full rounded border shadow-lg z-50 px-3 py-2 text-[12px]"
          style={{ background: colors.surface1, borderColor: colors.hairline, color: colors.inkSubtle }}>
          Nothing matches "{searchQuery}"
        </div>
      )}
    </div>
  );
}
