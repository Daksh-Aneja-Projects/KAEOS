import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router';
import {
  Bot, Activity, Search, Bell, Sun, Moon,
  ChevronDown, Settings as SettingsIcon, Database, Shield,
  MessageSquare, LogOut, Building2, X, Users, Rocket, Package,
  BarChart3, LayoutDashboard, Plug, ChevronRight, Briefcase,
  Landmark, Receipt, Wallet, Scale, ShieldAlert, FileText, ShieldCheck,
  Lock, Lightbulb, BookOpen, Clock, Heart, Compass, Target, TrendingUp,
  CheckSquare, Clipboard, Wrench, Server, GitPullRequest, Siren,
  Factory, UserPlus, Zap, FlaskConical, Menu
} from 'lucide-react';
import { ThemeProvider, useTheme } from './context/ThemeContext';
import { api, type PendingHITLItem, type AppNotification } from './api/client';
import { canSeeDepartment, DEPARTMENT_LABELS } from './lib/departments';
import { humanize } from './lib/format';
import { PAGE_PAD_X } from './lib/layout';
import KaeosLogo from './components/KaeosLogo';
import { AuthProvider, useAuth } from './context/AuthContext';
import { BrandingProvider, useBranding } from './context/BrandingContext';
import ThemeAdapter from './components/ThemeAdapter';
import ErrorBoundary from './components/ErrorBoundary';

// Pages
const LoginPage = lazy(() => import('./pages/LoginPage'));
// Public (rendered OUTSIDE the auth gate — no session required).
const AcceptInvite = lazy(() => import('./pages/AcceptInvite'));
const StatusPage = lazy(() => import('./pages/StatusPage'));

// ─── WORKFORCE (Primary) ───────────────────────────────────────────
const WorkforceDashboard = lazy(() => import('./pages/WorkforceDashboard'));
const DepartmentsHub = lazy(() => import('./pages/DepartmentsHub'));
const DepartmentDetail = lazy(() => import('./pages/DepartmentDetail'));
const DeploymentStudio = lazy(() => import('./pages/DeploymentStudio'));
const DomainPackMarketplace = lazy(() => import('./pages/DomainPackMarketplace'));
const WorkforceAnalytics = lazy(() => import('./pages/WorkforceAnalytics'));
const OrgPulse = lazy(() => import('./pages/OrgPulse'));
const MyWork = lazy(() => import('./pages/MyWork'));
const Automation = lazy(() => import('./pages/Automation'));
const ConnectorStudio = lazy(() => import('./pages/ConnectorStudio'));

// ─── HR DEPARTMENT ─────────────────────────────────────────────────
const HRDashboard = lazy(() => import('./pages/HRDashboard'));
const WorkforceView = lazy(() => import('./views/WorkforceView'));

// ─── FINANCE DEPARTMENT ─────────────────────────────────────────────
const FinanceDashboard = lazy(() => import('./pages/FinanceDashboard'));
const FinanceView = lazy(() => import('./views/FinanceView'));
const GeneralLedger = lazy(() => import('./pages/GeneralLedger'));

// ─── LEGAL DEPARTMENT ───────────────────────────────────────────────
const LegalDashboard = lazy(() => import('./pages/LegalDashboard'));
const LegalView = lazy(() => import('./views/LegalView'));

// ─── SUPPORT DEPARTMENT ─────────────────────────────────────────────
const SupportDashboard = lazy(() => import('./pages/SupportDashboard'));
const SupportView = lazy(() => import('./views/SupportView'));

// ─── SALES DEPARTMENT ───────────────────────────────────────────────
const SalesDashboard = lazy(() => import('./pages/SalesDashboard'));
const SalesView = lazy(() => import('./views/SalesView'));

// ─── OPERATIONS DEPARTMENT ──────────────────────────────────────────
const OperationsDashboard = lazy(() => import('./pages/OperationsDashboard'));
const OperationsView = lazy(() => import('./views/OperationsView'));
const EngineeringDashboard = lazy(() => import('./pages/EngineeringDashboard'));
const EngineeringView = lazy(() => import('./views/EngineeringView'));

// ─── REGULATED VERTICALS (Healthcare · Lending · Procurement) ───────
const HealthcareView = lazy(() => import('./views/HealthcareView'));
const LendingView = lazy(() => import('./views/LendingView'));
const ProcurementView = lazy(() => import('./views/ProcurementView'));

// ─── PLATFORM (Secondary) ─────────────────────────────────────────
const KnowledgeView = lazy(() => import('./views/KnowledgeView'));
const AgentsView = lazy(() => import('./views/AgentsView'));
const DecisionsView = lazy(() => import('./views/DecisionsView'));
const ComplianceChecker = lazy(() => import('./pages/ComplianceChecker'));
const SettingsView = lazy(() => import('./views/SettingsView'));
const UserManagement = lazy(() => import('./pages/UserManagement'));
const OperatorConsole = lazy(() => import('./pages/OperatorConsole'));

const RealityExperience = lazy(() => import('./pages/RealityExperience'));
const Foresight = lazy(() => import('./pages/Foresight'));
const PioneerLab = lazy(() => import('./pages/PioneerLab'));

// ─── v2 AI FOUNDRY + CLIENT ONBOARDING ─────────────────────────────
const AIFoundry = lazy(() => import('./pages/AIFoundry'));
const ProvingGround = lazy(() => import('./pages/ProvingGround'));
const ClientOnboarding = lazy(() => import('./pages/ClientOnboarding'));
const GettingStarted = lazy(() => import('./pages/GettingStarted'));

// Chat Copilot
const ChatCopilot = lazy(() => import('./components/ChatCopilot'));

// ─── Navigation Structure ──────────────────────────────────────────

type NavSection = { title: string; items: NavItem[]; collapsed?: boolean };
type NavItem = { path: string; label: string; icon: React.ElementType; badge?: string; adminOnly?: boolean };

const WORKFORCE_NAV: NavItem[] = [
  // Daily-use first: the dashboard and the user's personal inbox lead.
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/my-work', label: 'My Work', icon: Briefcase },
  // Departments (what you run) → Marketplace (browse & add) → Deploy wizard is
  // reached from a marketplace pack, so it's a flow, not a standalone nav item.
  { path: '/departments', label: 'Departments', icon: Building2 },
  { path: '/marketplace', label: 'Marketplace', icon: Package },
  { path: '/integrations', label: 'Integrations', icon: Plug },
  { path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { path: '/pulse', label: 'Org Pulse', icon: Activity },
  { path: '/automation', label: 'Automation', icon: Zap },
  // Onboarding lives at the bottom (one-time, not daily).
  { path: '/getting-started', label: 'Getting Started', icon: Compass },
];

// Department sub-sections are navigated via each department page's in-view tabs
// (the single source of truth), NOT via the sidebar — this is what removed the
// old sidebar/top-bar navigation duplication.

const PLATFORM_NAV: NavItem[] = [
  // Daily-use first.
  { path: '/platform/knowledge', label: 'Knowledge', icon: Database },
  { path: '/platform/agents', label: 'Agents', icon: Bot },
  { path: '/platform/decisions', label: 'Decisions', icon: Activity },
  { path: '/platform/proving-ground', label: 'Proving Ground', icon: ShieldCheck },
  { path: '/platform/compliance-checker', label: 'Compliance Checker', icon: Scale },
  // Tooling next.
  { path: '/platform/foundry', label: 'AI Foundry', icon: Factory },
  { path: '/platform/reality', label: 'Reality Experience', icon: Rocket },
  { path: '/platform/foresight', label: 'Foresight', icon: Compass },
  { path: '/platform/pioneer-lab', label: 'Pioneer Lab', icon: FlaskConical },
  // Admin/setup last.
  { path: '/platform/onboarding', label: 'Client Onboarding', icon: UserPlus, adminOnly: true },
  { path: '/platform/operator', label: 'Operator Console', icon: Server, adminOnly: true },
  { path: '/platform/users', label: 'User Management', icon: Shield, adminOnly: true },
  { path: '/platform/settings', label: 'Settings', icon: SettingsIcon },
];

// A nav link renders a 3px active border and then px-3, so its icon sits 15px
// from the nav container's content edge. Section labels use the same inset so
// the sidebar reads as one column instead of two ragged ones.
const SIDEBAR_LABEL_INSET = 'pl-[15px] pr-3';

// The sidebar brand chip: the tenant's logo when set (falls back to the KAEOS
// mark if the URL is unset or fails to load), otherwise the KAEOS mark.
function SidebarLogo({ logoUrl, primary }: { logoUrl: string | null; primary: string }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [logoUrl]);
  if (logoUrl && !broken) {
    return (
      <img src={logoUrl} alt="" onError={() => setBroken(true)}
        className="w-7 h-7 rounded object-contain" style={{ background: '#ffffff' }} />
    );
  }
  return (
    <div className="w-7 h-7 rounded flex items-center justify-center" style={{ background: primary }}>
      <KaeosLogo className="w-5 h-5" color="#ffffff" />
    </div>
  );
}

function SidebarNavLink({ item, colors }: { item: NavItem; colors: Record<string, string> }) {
  // `end` on every link: NavLink prefix-matches by default, so on
  // /departments/support/tickets the sidebar highlighted "Departments",
  // "Support Overview" AND "Ticket Queue" at once - the user could not tell
  // where they were. Only the exact route is active now.
  return (
    <NavLink to={item.path} end
      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] transition-all duration-200"
      style={({ isActive }) => ({
        background: isActive ? colors.navActive : 'transparent',
        color: isActive ? colors.navActiveText : colors.inkSubtle,
        borderLeft: isActive ? `3px solid ${colors.primary}` : '3px solid transparent',
        fontWeight: isActive ? 500 : 400,
      })}>
      <item.icon className="w-4 h-4 flex-shrink-0" />
      <span className="truncate">{item.label}</span>
      {item.badge && (
        <span className="ml-auto text-[11px] font-mono px-1.5 py-0.5 rounded-full opacity-50"
          style={{ background: colors.primary + '15', color: colors.primary }}>
          {item.badge}
        </span>
      )}
    </NavLink>
  );
}

function Shell() {
  const { theme, toggle, colors } = useTheme();
  const { user, logout, isAdmin } = useAuth();
  const { brand } = useBranding();
  const [domain, setDomain] = useState('All Domains');
  const [domainOpen, setDomainOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState<PendingHITLItem[]>([]);
  const [orgNotifs, setOrgNotifs] = useState<AppNotification[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [platformCollapsed, setPlatformCollapsed] = useState(true);
  // Below `md` the sidebar is an off-canvas drawer; at `md`+ it is always-on
  // and this flag is inert. HITL approvals are the daily touchpoint, so the
  // shell has to survive a phone.
  const [navOpen, setNavOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const notifButtonRef = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  // Navigating on mobile should dismiss the drawer, otherwise it covers the
  // page the user just asked for.
  useEffect(() => { setNavOpen(false); }, [location.pathname]);

  // Deep surfaces (e.g. the Hierarchy view's Conductor card) open the copilot
  // without prop-drilling through the whole tree.
  useEffect(() => {
    const open = () => setChatOpen(true);
    window.addEventListener('kaeos-open-copilot', open);
    return () => window.removeEventListener('kaeos-open-copilot', open);
  }, []);

  // Department-scoped RBAC: a scoped user's sidebar shows only their own
  // department entry; every other department's operational surface is hidden.
  // Cross-domain aggregates (Dashboard, Org Pulse, Analytics, Reality
  // Experience, My Work) stay visible on purpose: correlating signal across
  // departments is the product's IP, and the backend only gates other
  // departments' RECORDS and ACTIONS, not the org-level insight.
  const userDept = user?.department || null;
  const workforceNav: NavItem[] = WORKFORCE_NAV.map(n =>
    n.path === '/departments' && userDept
      ? {
          ...n,
          path: `/departments/${userDept}`,
          label: (DEPARTMENT_LABELS as Record<string, string>)[userDept] || 'My Department',
        }
      : n,
  );

  // Notifications: real pending human-in-the-loop approvals (the actionable
  // queue), polled every 30s. The bell badge lights only when there are items.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api.getPendingHITL()
        .then(d => { if (!cancelled) setNotifs(Array.isArray(d) ? d : []); })
        .catch(() => { if (!cancelled) setNotifs([]); });
      // Org notifications (SLA escalations, @mentions, automation alerts).
      api.getNotifications(true, 10)
        .then(d => { if (!cancelled) setOrgNotifs(d.items || []); })
        .catch(() => { if (!cancelled) setOrgNotifs([]); });
    };
    load();
    const t = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

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
        setNotifOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

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
  
  const DOMAINS = ['All Domains', 'HR', 'Finance', 'Engineering', 'Sales', 'Support'];

  // Which department (if any) the current route is under — used only for a small
  // sidebar context indicator, not to render duplicate sub-navigation.
  const DEPARTMENT_CONTEXT: { slug: string; label: string; color: string }[] = [
    { slug: 'hr', label: 'Human Resources', color: '#22c55e' },
    { slug: 'finance', label: 'Finance', color: '#ec4899' },
    { slug: 'legal', label: 'Legal & Compliance', color: '#6366f1' },
    { slug: 'support', label: 'Customer Support', color: '#3b82f6' },
    { slug: 'sales', label: 'Sales & CRM', color: '#f59e0b' },
    { slug: 'operations', label: 'Operations', color: '#ef4444' },
    { slug: 'engineering', label: 'Engineering & IT Ops', color: '#6366f1' },
    { slug: 'healthcare', label: 'Healthcare', color: '#14b8a6' },
    { slug: 'lending', label: 'Lending & Credit', color: '#d97706' },
    { slug: 'procurement', label: 'Procurement', color: '#8b5cf6' },
  ];
  const activeDepartment = DEPARTMENT_CONTEXT.find(
    d => location.pathname.startsWith(`/departments/${d.slug}`),
  );

  // Roving keyboard nav for the search-results and notification dropdowns:
  // ArrowDown/Up move between [data-menuitem] buttons, Escape closes.
  const focusMenuItem = (container: HTMLElement, dir: 1 | -1) => {
    const items = Array.from(container.querySelectorAll<HTMLButtonElement>('[data-menuitem]'));
    if (!items.length) return;
    const idx = items.indexOf(document.activeElement as HTMLButtonElement);
    const nextIdx = idx === -1 ? (dir === 1 ? 0 : items.length - 1) : (idx + dir + items.length) % items.length;
    items[nextIdx].focus();
  };
  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); focusMenuItem(e.currentTarget, 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusMenuItem(e.currentTarget, -1); }
    else if (e.key === 'Escape') { setSearchFocused(false); setSearchQuery(''); searchRef.current?.focus(); }
  };
  const handleNotifKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); focusMenuItem(e.currentTarget, 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusMenuItem(e.currentTarget, -1); }
    else if (e.key === 'Escape') { setNotifOpen(false); notifButtonRef.current?.focus(); }
  };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: colors.surface1, color: colors.ink, fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }}>
      {/* Mobile drawer scrim. Desktop (md+) never renders it. */}
      {navOpen && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          style={{ background: 'rgba(0,0,0,0.5)' }}
          onClick={() => setNavOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar — off-canvas drawer below md, static column at md+ */}
      <aside
        className={`w-[240px] flex flex-col flex-shrink-0 border-r overflow-hidden
          fixed inset-y-0 left-0 z-50 transition-transform duration-200 ease-out
          md:static md:z-auto md:translate-x-0
          ${navOpen ? 'translate-x-0' : '-translate-x-full'}`}
        style={{ borderColor: colors.hairline, background: colors.canvas }}
      >
        <div className="h-14 flex items-center px-5 border-b flex-shrink-0" style={{ borderColor: colors.hairline }}>
          <NavLink to="/" className="flex items-center gap-2.5 w-full">
            <SidebarLogo logoUrl={brand.logo_url} primary={colors.primary} />
            <div className="flex flex-col min-w-0">
              <span className="text-[16px] font-semibold tracking-tight truncate" style={{ color: colors.ink }}>{brand.product_name}</span>
              <span className="text-[11px] -mt-0.5 tracking-wide uppercase" style={{ color: colors.inkSubtle }}>Governed Autonomy</span>
            </div>
          </NavLink>
        </div>

        <div className="flex-1 overflow-y-auto py-2 px-3 space-y-1">
          {/* Section labels are inset by SIDEBAR_LABEL_INSET so they line up with
              the nav item ICONS below them, not with the nav item's outer edge.
              A nav link carries a 3px active border plus px-3, so its icon sits
              15px in; a label at px-1 sat 11px to the left of every icon. */}
          {/* WORKFORCE Section */}
          <div className={`${SIDEBAR_LABEL_INSET} pt-2 pb-1.5`}>
            <span className="text-[11px] font-bold uppercase tracking-widest" style={{ color: colors.primary }}>Workforce</span>
          </div>
          {workforceNav.map(n => (
            <SidebarNavLink key={n.path} item={n} colors={colors} />
          ))}

          {/* Department sub-sections are NOT duplicated here — they live as the
              in-view top-bar tabs on each department page (the single source of
              truth). The sidebar stops at the department to avoid the exact
              sidebar/top-bar duplication that used to exist. When inside a
              department, the "Departments" item above stays highlighted. */}
          {activeDepartment && (
            <div className={`${SIDEBAR_LABEL_INSET} pt-5 pb-1.5 flex items-center gap-1.5`}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: activeDepartment.color }} />
              <span className="text-[11px] font-bold uppercase tracking-widest" style={{ color: activeDepartment.color }}>
                {activeDepartment.label}
              </span>
            </div>
          )}

          {/* PLATFORM Section */}
          <div className={`${SIDEBAR_LABEL_INSET} pt-5 pb-1.5`}>
            <button aria-label="Toggle platform section" onClick={() => setPlatformCollapsed(!platformCollapsed)}
              className="flex items-center gap-1 w-full text-left">
              <span className="text-[11px] font-bold uppercase tracking-widest" style={{ color: colors.inkSubtle }}>Platform</span>
              <ChevronRight className={`w-3 h-3 transition-transform ${platformCollapsed ? '' : 'rotate-90'}`} style={{ color: colors.inkSubtle }} />
            </button>
          </div>
          {!platformCollapsed && PLATFORM_NAV
            .filter(n => !n.adminOnly || isAdmin)
            .map(n => (
              <SidebarNavLink key={n.path} item={n} colors={colors} />
            ))
          }
        </div>

        <div className="p-4 border-t flex-shrink-0" style={{ borderColor: colors.hairline }}>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded flex items-center justify-center text-[12px] font-bold"
              style={{ background: colors.primary + '20', color: colors.primary }}>
              {(user?.display_name || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="flex flex-col flex-1 min-w-0">
              <span className="text-[13px] font-medium truncate" style={{ color: colors.ink }}>{user?.display_name || 'User'}</span>
              <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{humanize(user?.role) || 'Viewer'}</span>
            </div>
            <button aria-label="Sign out" onClick={logout} title="Sign out" className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Area */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* Top Bar */}
        <header className={`h-14 flex items-center justify-between ${PAGE_PAD_X} border-b flex-shrink-0 z-10`} style={{ borderColor: colors.hairline, background: colors.surface1 }}>
          <div className="flex items-center gap-3 md:gap-4 min-w-0">
            {/* Drawer toggle — mobile only; the sidebar is always present at md+ */}
            <button
              aria-label="Open navigation"
              aria-expanded={navOpen}
              onClick={() => setNavOpen(true)}
              className="md:hidden p-1.5 rounded hover:bg-surface2 transition-colors flex-shrink-0"
              style={{ color: colors.ink }}
            >
              <Menu className="w-5 h-5" />
            </button>
            {/* Domain Selector */}
            <div className="relative">
              <div onClick={() => setDomainOpen(!domainOpen)} className="flex items-center gap-2 px-3 py-1.5 rounded border cursor-pointer hover:bg-surface2 transition-colors" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                <span className="text-[13px] font-medium" style={{ color: colors.ink }}>Domain: {domain}</span>
                <ChevronDown className="w-3.5 h-3.5" style={{ color: colors.inkSubtle }} />
              </div>
              {domainOpen && (
                <div className="absolute top-full left-0 mt-1 w-full rounded border shadow-lg z-50 overflow-hidden" style={{ background: colors.surface1, borderColor: colors.hairline }}>
                  {DOMAINS.map(d => (
                    <div key={d} onClick={() => { setDomain(d); setDomainOpen(false); }} className="px-3 py-1.5 text-[13px] cursor-pointer hover:bg-surface2 transition-colors" style={{ color: colors.ink }}>
                      {d}
                    </div>
                  ))}
                </div>
              )}
            </div>
            {/* System Status — secondary chrome, yields space on small screens */}
            <div className="hidden lg:flex items-center gap-2 px-2 py-1 rounded" style={{ background: 'rgba(34, 197, 94, 0.1)' }}>
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-[11px] font-medium text-green-500">System Online</span>
            </div>
          </div>

          <div className="flex items-center gap-2 md:gap-3">
            {/* Fixed-width search would overflow a phone; it is keyboard-driven
                (⌘K) chrome, so it yields below md rather than shrinking. */}
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
            <div className="relative" onKeyDown={handleNotifKeyDown}>
              <button ref={notifButtonRef} aria-label="Notifications" aria-expanded={notifOpen} aria-haspopup="true"
                onClick={() => setNotifOpen(o => !o)}
                className="p-1.5 rounded hover:bg-surface2 transition-colors relative"
                style={{ color: notifOpen ? colors.primary : colors.inkSubtle }}>
                <Bell className="w-4 h-4" />
                {(notifs.length + orgNotifs.length) > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-1 rounded-full text-[11px] font-bold text-white flex items-center justify-center"
                    style={{ background: colors.error }}>{(notifs.length + orgNotifs.length) > 9 ? '9+' : (notifs.length + orgNotifs.length)}</span>
                )}
              </button>
              {notifOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setNotifOpen(false)} />
                  <div role="menu" aria-label="Notifications" className="absolute top-full right-0 mt-1 w-80 rounded-lg border shadow-xl z-50 overflow-hidden"
                    style={{ background: colors.surface1, borderColor: colors.hairline }}>
                    <div className="px-3 py-2.5 border-b flex items-center justify-between" style={{ borderColor: colors.hairline }}>
                      <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>Notifications</span>
                      <span className="text-[11px] px-1.5 py-0.5 rounded-full"
                        style={{ background: notifs.length ? colors.error + '20' : colors.surface3, color: notifs.length ? colors.error : colors.inkSubtle }}>
                        {notifs.length} pending
                      </span>
                    </div>
                    <div className="max-h-[360px] overflow-y-auto">
                      {/* Org notifications: SLA escalations, @mentions, automation alerts */}
                      {orgNotifs.map(n => (
                        <button key={n.id} type="button" role="menuitem" data-menuitem
                          onClick={() => { navigate('/pulse'); setNotifOpen(false); }}
                          className="w-full text-left px-3 py-2.5 cursor-pointer hover:bg-surface2 transition-colors border-b block focus:outline-none focus-visible:bg-surface2"
                          style={{ borderColor: colors.hairline }}>
                          <div className="flex items-start gap-2">
                            <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5"
                              style={{ background: (n.severity === 'critical' ? colors.error : colors.warning) + '20' }}>
                              <Activity className="w-3.5 h-3.5" style={{ color: n.severity === 'critical' ? colors.error : colors.warning }} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{n.title}</div>
                              {n.description && <div className="text-[11px] mt-0.5 truncate" style={{ color: colors.inkSubtle }}>{n.description}</div>}
                            </div>
                          </div>
                        </button>
                      ))}
                      {notifs.length === 0 && orgNotifs.length === 0 ? (
                        <div className="px-3 py-8 text-center">
                          <Bell className="w-6 h-6 mx-auto mb-2" style={{ color: colors.inkTertiary }} />
                          <div className="text-[12px]" style={{ color: colors.inkSubtle }}>You're all caught up</div>
                          <div className="text-[11px] mt-0.5" style={{ color: colors.inkTertiary }}>No decisions or alerts awaiting you</div>
                        </div>
                      ) : notifs.map(n => (
                        <button key={n.id} type="button" role="menuitem" data-menuitem
                          onClick={() => { navigate('/platform/decisions'); setNotifOpen(false); }}
                          className="w-full text-left px-3 py-2.5 cursor-pointer hover:bg-surface2 transition-colors border-b block focus:outline-none focus-visible:bg-surface2"
                          style={{ borderColor: colors.hairline }}>
                          <div className="flex items-start gap-2">
                            <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5" style={{ background: colors.warning + '20' }}>
                              <Shield className="w-3.5 h-3.5" style={{ color: colors.warning }} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{n.task_intent || n.skill_id_name}</div>
                              <div className="text-[11px] mt-0.5" style={{ color: colors.inkSubtle }}>
                                Approval required{n.route_type ? ` · ${n.route_type === 'GATED_AGENT' ? 'Pipeline gate' : humanize(n.route_type)}` : ''}
                              </div>
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                    {notifs.length > 0 && (
                      <button type="button" role="menuitem" data-menuitem
                        onClick={() => { navigate('/platform/decisions'); setNotifOpen(false); }}
                        className="w-full px-3 py-2 text-center text-[12px] cursor-pointer hover:bg-surface2 transition-colors font-medium focus:outline-none focus-visible:bg-surface2"
                        style={{ color: colors.primary }}>
                        Review all in Decisions
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
            {/* Chat Copilot Toggle */}
            <button aria-label="Toggle KAEOS Copilot" onClick={() => setChatOpen(!chatOpen)}
              className="p-1.5 rounded hover:bg-surface2 transition-colors relative"
              style={{ color: chatOpen ? colors.primary : colors.inkSubtle }}>
              <MessageSquare className="w-4 h-4" />
            </button>
            <button aria-label="Toggle theme" onClick={toggle} className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </header>

        {/* Dynamic Content - URL-based routing */}
        <div className="flex-1 overflow-y-auto" style={{ background: colors.canvas }}>
          {/* key by pathname so a crash in one module doesn't stick to the next route */}
          <ErrorBoundary key={location.pathname} fallbackTitle="Module encountered an error">
            <Suspense fallback={
              <div className="h-full w-full flex items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                  <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  <span className="text-[13px]" style={{ color: colors.inkSubtle }}>Loading Module...</span>
                </div>
              </div>
            }>
              <Routes>
                {/* WORKFORCE */}
                <Route path="/" element={<ThemeAdapter><WorkforceDashboard domain={domain} /></ThemeAdapter>} />
                <Route path="/departments" element={<ThemeAdapter><DepartmentsHub /></ThemeAdapter>} />
                <Route path="/deploy" element={<ThemeAdapter><DeploymentStudio domain={domain} /></ThemeAdapter>} />
                <Route path="/marketplace" element={<ThemeAdapter><DomainPackMarketplace domain={domain} /></ThemeAdapter>} />
                <Route path="/integrations" element={<ThemeAdapter><ConnectorStudio domain={domain} /></ThemeAdapter>} />
                <Route path="/analytics" element={<ThemeAdapter><WorkforceAnalytics domain={domain} /></ThemeAdapter>} />
                <Route path="/pulse" element={<ThemeAdapter><OrgPulse domain={domain} /></ThemeAdapter>} />
                <Route path="/my-work" element={<ThemeAdapter><MyWork domain={domain} /></ThemeAdapter>} />
                <Route path="/automation" element={<ThemeAdapter><Automation domain={domain} /></ThemeAdapter>} />

                {/* HR DEPARTMENT */}
                <Route path="/departments/hr" element={<ThemeAdapter><HRDashboard domain={domain} /></ThemeAdapter>} />
                <Route path="/departments/hr/recruiting" element={<ThemeAdapter><WorkforceView domain={domain} defaultTab="recruiting" /></ThemeAdapter>} />
                <Route path="/departments/hr/employees" element={<ThemeAdapter><WorkforceView domain={domain} defaultTab="employees" /></ThemeAdapter>} />
                <Route path="/departments/hr/time" element={<ThemeAdapter><WorkforceView domain={domain} defaultTab="time" /></ThemeAdapter>} />
                <Route path="/departments/hr/performance" element={<ThemeAdapter><WorkforceView domain={domain} defaultTab="performance" /></ThemeAdapter>} />

                {/* FINANCE DEPARTMENT */}
                <Route path="/departments/finance" element={<ThemeAdapter><FinanceDashboard /></ThemeAdapter>} />
                <Route path="/departments/finance/ap" element={<ThemeAdapter><FinanceView domain={domain} defaultTab="ap" /></ThemeAdapter>} />
                <Route path="/departments/finance/ar" element={<ThemeAdapter><FinanceView domain={domain} defaultTab="ar" /></ThemeAdapter>} />
                <Route path="/departments/finance/budgets" element={<ThemeAdapter><FinanceView domain={domain} defaultTab="budgets" /></ThemeAdapter>} />
                <Route path="/departments/finance/expenses" element={<ThemeAdapter><FinanceView domain={domain} defaultTab="expenses" /></ThemeAdapter>} />
                <Route path="/departments/finance/tax" element={<ThemeAdapter><FinanceView domain={domain} defaultTab="tax" /></ThemeAdapter>} />
                <Route path="/departments/finance/audit" element={<ThemeAdapter><FinanceView domain={domain} defaultTab="audit" /></ThemeAdapter>} />
                <Route path="/departments/finance/gl" element={<ThemeAdapter><GeneralLedger /></ThemeAdapter>} />

                {/* LEGAL DEPARTMENT */}
                <Route path="/departments/legal" element={<ThemeAdapter><LegalDashboard /></ThemeAdapter>} />
                <Route path="/departments/legal/contracts" element={<ThemeAdapter><LegalView domain={domain} defaultTab="contracts" /></ThemeAdapter>} />
                <Route path="/departments/legal/compliance" element={<ThemeAdapter><LegalView domain={domain} defaultTab="compliance" /></ThemeAdapter>} />
                <Route path="/departments/legal/litigation" element={<ThemeAdapter><LegalView domain={domain} defaultTab="litigation" /></ThemeAdapter>} />
                <Route path="/departments/legal/privacy" element={<ThemeAdapter><LegalView domain={domain} defaultTab="privacy" /></ThemeAdapter>} />
                <Route path="/departments/legal/ip" element={<ThemeAdapter><LegalView domain={domain} defaultTab="ip" /></ThemeAdapter>} />

                {/* SUPPORT DEPARTMENT */}
                <Route path="/departments/support" element={<ThemeAdapter><SupportDashboard /></ThemeAdapter>} />
                <Route path="/departments/support/tickets" element={<ThemeAdapter><SupportView domain={domain} defaultTab="tickets" /></ThemeAdapter>} />
                <Route path="/departments/support/kb" element={<ThemeAdapter><SupportView domain={domain} defaultTab="kb" /></ThemeAdapter>} />
                <Route path="/departments/support/sla" element={<ThemeAdapter><SupportView domain={domain} defaultTab="sla" /></ThemeAdapter>} />
                <Route path="/departments/support/feedback" element={<ThemeAdapter><SupportView domain={domain} defaultTab="feedback" /></ThemeAdapter>} />

                {/* SALES DEPARTMENT */}
                <Route path="/departments/sales" element={<ThemeAdapter><SalesDashboard /></ThemeAdapter>} />
                <Route path="/departments/sales/pipeline" element={<ThemeAdapter><SalesView domain={domain} defaultTab="opportunities" /></ThemeAdapter>} />
                <Route path="/departments/sales/leads" element={<ThemeAdapter><SalesView domain={domain} defaultTab="leads" /></ThemeAdapter>} />
                <Route path="/departments/sales/forecasts" element={<ThemeAdapter><SalesView domain={domain} defaultTab="forecasts" /></ThemeAdapter>} />
                <Route path="/departments/sales/accounts" element={<ThemeAdapter><SalesView domain={domain} defaultTab="accounts" /></ThemeAdapter>} />

                {/* OPERATIONS DEPARTMENT */}
                {/* Engineering & IT Ops - the largest slice of enterprise AI spend */}
                <Route path="/departments/engineering" element={<ThemeAdapter><EngineeringDashboard /></ThemeAdapter>} />
                <Route path="/departments/engineering/services" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="services" /></ThemeAdapter>} />
                <Route path="/departments/engineering/pull-requests" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="pull-requests" /></ThemeAdapter>} />
                <Route path="/departments/engineering/deployments" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="deployments" /></ThemeAdapter>} />
                <Route path="/departments/engineering/incidents" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="incidents" /></ThemeAdapter>} />
                <Route path="/departments/engineering/postmortems" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="postmortems" /></ThemeAdapter>} />
                <Route path="/departments/engineering/oncall" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="oncall" /></ThemeAdapter>} />

                <Route path="/departments/operations" element={<ThemeAdapter><OperationsDashboard /></ThemeAdapter>} />
                <Route path="/departments/operations/projects" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="projects" /></ThemeAdapter>} />
                <Route path="/departments/operations/resources" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="resources" /></ThemeAdapter>} />
                <Route path="/departments/operations/vendors" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="vendors" /></ThemeAdapter>} />
                <Route path="/departments/operations/procurement" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="procurement" /></ThemeAdapter>} />
                <Route path="/departments/operations/quality" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="quality" /></ThemeAdapter>} />

                {/* HEALTHCARE DEPARTMENT */}
                <Route path="/departments/healthcare" element={<ThemeAdapter><HealthcareView domain={domain} defaultTab="overview" /></ThemeAdapter>} />
                <Route path="/departments/healthcare/encounters" element={<ThemeAdapter><HealthcareView domain={domain} defaultTab="encounters" /></ThemeAdapter>} />
                <Route path="/departments/healthcare/disclosures" element={<ThemeAdapter><HealthcareView domain={domain} defaultTab="disclosures" /></ThemeAdapter>} />
                <Route path="/departments/healthcare/consent" element={<ThemeAdapter><HealthcareView domain={domain} defaultTab="consent" /></ThemeAdapter>} />
                <Route path="/departments/healthcare/tasks" element={<ThemeAdapter><HealthcareView domain={domain} defaultTab="tasks" /></ThemeAdapter>} />

                {/* LENDING DEPARTMENT */}
                <Route path="/departments/lending" element={<ThemeAdapter><LendingView domain={domain} defaultTab="overview" /></ThemeAdapter>} />
                <Route path="/departments/lending/applications" element={<ThemeAdapter><LendingView domain={domain} defaultTab="applications" /></ThemeAdapter>} />
                <Route path="/departments/lending/underwriting" element={<ThemeAdapter><LendingView domain={domain} defaultTab="underwriting" /></ThemeAdapter>} />
                <Route path="/departments/lending/adverse-action" element={<ThemeAdapter><LendingView domain={domain} defaultTab="adverse" /></ThemeAdapter>} />

                {/* PROCUREMENT DEPARTMENT */}
                <Route path="/departments/procurement" element={<ThemeAdapter><ProcurementView domain={domain} defaultTab="overview" /></ThemeAdapter>} />
                <Route path="/departments/procurement/requisitions" element={<ThemeAdapter><ProcurementView domain={domain} defaultTab="requisitions" /></ThemeAdapter>} />
                <Route path="/departments/procurement/purchase-orders" element={<ThemeAdapter><ProcurementView domain={domain} defaultTab="purchase-orders" /></ThemeAdapter>} />
                <Route path="/departments/procurement/goods-receipts" element={<ThemeAdapter><ProcurementView domain={domain} defaultTab="goods-receipts" /></ThemeAdapter>} />
                <Route path="/departments/procurement/vendors" element={<ThemeAdapter><ProcurementView domain={domain} defaultTab="vendors" /></ThemeAdapter>} />


                {/* DEPARTMENT DETAIL (dynamic) */}
                <Route path="/departments/:deptId" element={<ThemeAdapter><DepartmentDetail domain={domain} /></ThemeAdapter>} />

                {/* PLATFORM */}
                <Route path="/getting-started" element={<ThemeAdapter><GettingStarted /></ThemeAdapter>} />
                <Route path="/platform/foundry" element={<ThemeAdapter><AIFoundry /></ThemeAdapter>} />
                <Route path="/platform/onboarding" element={<ThemeAdapter><ClientOnboarding /></ThemeAdapter>} />
                <Route path="/platform/reality" element={<ThemeAdapter><RealityExperience /></ThemeAdapter>} />
                <Route path="/platform/foresight" element={<ThemeAdapter><Foresight /></ThemeAdapter>} />
                <Route path="/platform/pioneer-lab" element={<ThemeAdapter><PioneerLab /></ThemeAdapter>} />
                <Route path="/platform/knowledge" element={<ThemeAdapter><KnowledgeView domain={domain} /></ThemeAdapter>} />
                <Route path="/platform/agents" element={<ThemeAdapter><AgentsView domain={domain} /></ThemeAdapter>} />
                <Route path="/platform/decisions" element={<ThemeAdapter><DecisionsView domain={domain} /></ThemeAdapter>} />
                <Route path="/platform/proving-ground" element={<ThemeAdapter><ProvingGround /></ThemeAdapter>} />
                <Route path="/platform/compliance-checker" element={<ThemeAdapter><ComplianceChecker /></ThemeAdapter>} />
                {/* Company Brain merged into Knowledge; Trust merged into Decisions (Governance tab). */}
                <Route path="/platform/brain" element={<Navigate to="/platform/knowledge" replace />} />
                <Route path="/platform/trust" element={<Navigate to="/platform/decisions" replace />} />
                <Route path="/platform/users" element={<ThemeAdapter><UserManagement /></ThemeAdapter>} />
                <Route path="/platform/operator" element={<ThemeAdapter><OperatorConsole /></ThemeAdapter>} />
                <Route path="/platform/settings" element={<ThemeAdapter><SettingsView domain={domain} /></ThemeAdapter>} />

                {/* Fallback — surface broken links instead of silently rendering
                    the dashboard (which used to mask 404s). */}
                <Route path="*" element={
                  <ThemeAdapter>
                    <div className="h-full flex flex-col items-center justify-center gap-4 text-center">
                      <div className="text-[48px] font-bold opacity-20">404</div>
                      <div className="text-[15px] font-semibold">Page not found</div>
                      <NavLink to="/" className="text-[13px] underline opacity-70">Back to Dashboard</NavLink>
                    </div>
                  </ThemeAdapter>
                } />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </div>

        {/* Chat Copilot - always mounted so its bottom-right launcher is
            available on every screen; the header button also toggles it. */}
        <Suspense fallback={null}>
          <ChatCopilot open={chatOpen} onOpenChange={setChatOpen} />
        </Suspense>
      </main>
    </div>
  );
}

function AuthGuard() {
  const { user, loading } = useAuth();
  const { colors } = useTheme();

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center" style={{ background: colors.canvas }}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
          <span className="text-[13px]" style={{ color: colors.inkSubtle }}>Loading KAEOS...</span>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <Suspense fallback={null}>
        <LoginPage />
      </Suspense>
    );
  }

  // Branding is fetched inside the authed shell (a /branding call needs a
  // session), then applied app-wide.
  return (
    <BrandingProvider>
      <Shell />
    </BrandingProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        {/* /accept-invite is the one PUBLIC route: an invited user has no
            session yet, so it must render before the auth gate. Everything
            else falls through to AuthGuard, which owns the app's own Routes. */}
        <Routes>
          <Route path="/accept-invite" element={
            <Suspense fallback={null}>
              <AcceptInvite />
            </Suspense>
          } />
          {/* Public, unauthenticated status page — rendered before the auth gate. */}
          <Route path="/status" element={
            <Suspense fallback={null}>
              <StatusPage />
            </Suspense>
          } />
          <Route path="*" element={<AuthGuard />} />
        </Routes>
      </AuthProvider>
    </ThemeProvider>
  );
}
