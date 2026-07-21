import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router-dom';
import {
  Bot, Activity, Search, Bell, Sun, Moon,
  ChevronDown, Settings as SettingsIcon, Database, Shield,
  MessageSquare, LogOut, Building2, X, Users, Rocket, Package,
  BarChart3, LayoutDashboard, Plug, ChevronRight, Briefcase,
  Landmark, Receipt, Wallet, Scale, ShieldAlert, FileText, ShieldCheck,
  Lock, Lightbulb, BookOpen, Clock, Heart, Compass, Target, TrendingUp,
  CheckSquare, Clipboard, Wrench, Server, GitPullRequest, Siren,
  Factory, UserPlus, Zap
} from 'lucide-react';
import { ThemeProvider, useTheme } from './context/ThemeContext';
import { api, type PendingHITLItem, type AppNotification } from './api/client';
import KaeosLogo from './components/KaeosLogo';
import { AuthProvider, useAuth } from './context/AuthContext';
import ThemeAdapter from './components/ThemeAdapter';
import ErrorBoundary from './components/ErrorBoundary';

// Pages
const LoginPage = lazy(() => import('./pages/LoginPage'));

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
const EngineeringView = lazy(() => import('./views/EngineeringView'));

// ─── PLATFORM (Secondary) ─────────────────────────────────────────
const KnowledgeView = lazy(() => import('./views/KnowledgeView'));
const AgentsView = lazy(() => import('./views/AgentsView'));
const DecisionsView = lazy(() => import('./views/DecisionsView'));
const SettingsView = lazy(() => import('./views/SettingsView'));
const UserManagement = lazy(() => import('./pages/UserManagement'));

const RealityExperience = lazy(() => import('./pages/RealityExperience'));

// ─── v2 AI FOUNDRY + CLIENT ONBOARDING ─────────────────────────────
const AIFoundry = lazy(() => import('./pages/AIFoundry'));
const ClientOnboarding = lazy(() => import('./pages/ClientOnboarding'));
const GettingStarted = lazy(() => import('./pages/GettingStarted'));

// Chat Copilot
const ChatCopilot = lazy(() => import('./components/ChatCopilot'));

// ─── Navigation Structure ──────────────────────────────────────────

type NavSection = { title: string; items: NavItem[]; collapsed?: boolean };
type NavItem = { path: string; label: string; icon: React.ElementType; badge?: string; adminOnly?: boolean };

const WORKFORCE_NAV: NavItem[] = [
  { path: '/getting-started', label: 'Getting Started', icon: Compass },
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  // Departments (what you run) → Marketplace (browse & add) → Deploy wizard is
  // reached from a marketplace pack, so it's a flow, not a standalone nav item.
  { path: '/departments', label: 'Departments', icon: Building2 },
  { path: '/marketplace', label: 'Marketplace', icon: Package },
  { path: '/integrations', label: 'Integrations', icon: Plug },
  { path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { path: '/pulse', label: 'Org Pulse', icon: Activity },
  { path: '/my-work', label: 'My Work', icon: Briefcase },
  { path: '/automation', label: 'Automation', icon: Zap },
];

const HR_NAV: NavItem[] = [
  { path: '/departments/hr', label: 'HR Overview', icon: Briefcase },
  { path: '/departments/hr/recruiting', label: 'Recruiting', icon: Users },
  { path: '/departments/hr/employees', label: 'Employees', icon: Users },
  { path: '/departments/hr/time', label: 'Time & Leave', icon: Activity },
  { path: '/departments/hr/performance', label: 'Performance', icon: BarChart3 },
];

const FINANCE_NAV: NavItem[] = [
  { path: '/departments/finance', label: 'Finance Overview', icon: Landmark },
  { path: '/departments/finance/ap', label: 'Accounts Payable', icon: Receipt },
  { path: '/departments/finance/ar', label: 'Accounts Receivable', icon: Landmark },
  { path: '/departments/finance/budgets', label: 'Budgets & Forecasts', icon: BarChart3 },
  { path: '/departments/finance/expenses', label: 'Expense Reports', icon: Wallet },
  { path: '/departments/finance/tax', label: 'Tax Center', icon: Scale },
  { path: '/departments/finance/audit', label: 'Audit & SOX', icon: ShieldAlert },
];

const LEGAL_NAV: NavItem[] = [
  { path: '/departments/legal', label: 'Legal Overview', icon: Scale },
  { path: '/departments/legal/contracts', label: 'Contract Lifecycle', icon: FileText },
  { path: '/departments/legal/compliance', label: 'Compliance Oblig.', icon: ShieldCheck },
  { path: '/departments/legal/litigation', label: 'Litigation Support', icon: Landmark },
  { path: '/departments/legal/privacy', label: 'Privacy Operations', icon: Lock },
  { path: '/departments/legal/ip', label: 'Intellectual Property', icon: Lightbulb },
];

const SUPPORT_NAV: NavItem[] = [
  { path: '/departments/support', label: 'Support Overview', icon: MessageSquare },
  { path: '/departments/support/tickets', label: 'Ticket Queue', icon: MessageSquare },
  { path: '/departments/support/kb', label: 'Knowledge Base', icon: BookOpen },
  { path: '/departments/support/sla', label: 'SLA Dashboard', icon: Clock },
  { path: '/departments/support/feedback', label: 'CSAT Surveys', icon: Heart },
];

const SALES_NAV: NavItem[] = [
  { path: '/departments/sales', label: 'Sales Overview', icon: Compass },
  { path: '/departments/sales/pipeline', label: 'Deals Pipeline', icon: Compass },
  { path: '/departments/sales/leads', label: 'Inbound Leads', icon: Target },
  { path: '/departments/sales/forecasts', label: 'Forecasts', icon: TrendingUp },
  { path: '/departments/sales/accounts', label: 'Accounts', icon: Landmark },
];

const OPERATIONS_NAV: NavItem[] = [
  { path: '/departments/operations', label: 'Ops Overview', icon: CheckSquare },
  { path: '/departments/operations/projects', label: 'Project Portfolio', icon: CheckSquare },
  { path: '/departments/operations/resources', label: 'Team Allocations', icon: Users },
  { path: '/departments/operations/vendors', label: 'Supplier Operations', icon: Clipboard },
  { path: '/departments/operations/procurement', label: 'Purchases', icon: Wrench },
  { path: '/departments/operations/quality', label: 'QA & Inspections', icon: ShieldAlert },
];

const ENGINEERING_NAV: NavItem[] = [
  { path: '/departments/engineering', label: 'Service Catalog', icon: Server },
  { path: '/departments/engineering/pull-requests', label: 'Pull Requests', icon: GitPullRequest },
  { path: '/departments/engineering/deployments', label: 'Deployments', icon: Rocket },
  { path: '/departments/engineering/incidents', label: 'Incidents', icon: Siren },
  { path: '/departments/engineering/postmortems', label: 'Postmortems', icon: FileText },
];

const PLATFORM_NAV: NavItem[] = [
  { path: '/platform/foundry', label: 'AI Foundry', icon: Factory },
  { path: '/platform/onboarding', label: 'Client Onboarding', icon: UserPlus, adminOnly: true },
  { path: '/platform/reality', label: 'Reality Experience', icon: Rocket },
  { path: '/platform/knowledge', label: 'Knowledge', icon: Database },
  { path: '/platform/agents', label: 'Agents', icon: Bot },
  { path: '/platform/decisions', label: 'Decisions', icon: Activity },
  { path: '/platform/users', label: 'User Management', icon: Shield, adminOnly: true },
  { path: '/platform/settings', label: 'Settings', icon: SettingsIcon },
];

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
        <span className="ml-auto text-[9px] font-mono px-1.5 py-0.5 rounded-full opacity-50"
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
  const [domain, setDomain] = useState('All Domains');
  const [domainOpen, setDomainOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState<PendingHITLItem[]>([]);
  const [orgNotifs, setOrgNotifs] = useState<AppNotification[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [platformCollapsed, setPlatformCollapsed] = useState(true);
  const searchRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

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
    { path: '/platform/knowledge', label: 'Knowledge', keywords: 'rules skills topology extraction connectors' },
    { path: '/platform/agents', label: 'Agents', keywords: 'deploy blueprint ooda llm mcp marketplace' },
    { path: '/platform/decisions', label: 'Decisions', keywords: 'cockpit compliance provenance redteam hitl fairness debates governance trust' },
    { path: '/platform/settings', label: 'Settings', keywords: 'config ontology federated' },
    { path: '/platform/users', label: 'User Management', keywords: 'admin roles users rbac' },
    { path: '/platform/foundry', label: 'AI Foundry', keywords: 'foundry training dataset fine-tune model evolution learning v2' },
    { path: '/platform/onboarding', label: 'Client Onboarding', keywords: 'onboard tenant client provision new customer setup' },
    { path: '/getting-started', label: 'Getting Started', keywords: 'getting started onboarding checklist activate setup first' },
  ];
  const searchResults = searchQuery.length >= 2
    ? SEARCHABLE_MODULES.filter(m =>
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

  // Check if current route is under department sections
  const isHRActive = location.pathname.startsWith('/departments/hr');
  const isFinanceActive = location.pathname.startsWith('/departments/finance');
  const isLegalActive = location.pathname.startsWith('/departments/legal');
  const isSupportActive = location.pathname.startsWith('/departments/support');
  const isSalesActive = location.pathname.startsWith('/departments/sales');
  const isOperationsActive = location.pathname.startsWith('/departments/operations');
  const isEngineeringActive = location.pathname.startsWith('/departments/engineering');

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: colors.surface1, color: colors.ink, fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }}>
      {/* Sidebar */}
      <aside className="w-[240px] flex flex-col flex-shrink-0 border-r overflow-hidden" style={{ borderColor: colors.hairline, background: colors.canvas }}>
        <div className="h-14 flex items-center px-5 border-b flex-shrink-0" style={{ borderColor: colors.hairline }}>
          <NavLink to="/" className="flex items-center gap-2.5 w-full">
            <div className="w-7 h-7 rounded flex items-center justify-center" style={{ background: colors.primary }}>
              <KaeosLogo className="w-5 h-5" color="#ffffff" />
            </div>
            <div className="flex flex-col">
              <span className="text-[16px] font-semibold tracking-tight" style={{ color: colors.ink }}>KAEOS</span>
              <span className="text-[9px] -mt-0.5 tracking-wide uppercase" style={{ color: colors.inkSubtle }}>Enterprise Workforce OS</span>
            </div>
          </NavLink>
        </div>

        <div className="flex-1 overflow-y-auto py-2 px-3 space-y-1">
          {/* WORKFORCE Section */}
          <div className="px-1 pt-2 pb-1">
            <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: colors.primary }}>Workforce</span>
          </div>
          {WORKFORCE_NAV.map(n => (
            <SidebarNavLink key={n.path} item={n} colors={colors} />
          ))}

          {/* HR DEPARTMENT Section (visible when HR is active/being viewed) */}
          {isHRActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#22c55e' }}>HR Department</span>
              </div>
              {HR_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}

          {/* FINANCE DEPARTMENT Section */}
          {isFinanceActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#ec4899' }}>Finance</span>
              </div>
              {FINANCE_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}

          {/* LEGAL DEPARTMENT Section */}
          {isLegalActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#6366f1' }}>Legal & Compliance</span>
              </div>
              {LEGAL_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}

          {/* SUPPORT DEPARTMENT Section */}
          {isSupportActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#3b82f6' }}>Customer Support</span>
              </div>
              {SUPPORT_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}

          {/* SALES DEPARTMENT Section */}
          {isSalesActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#f59e0b' }}>Sales & CRM</span>
              </div>
              {SALES_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}

          {/* OPERATIONS DEPARTMENT Section */}
          {isOperationsActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#ef4444' }}>Operations</span>
              </div>
              {OPERATIONS_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}

          {/* ENGINEERING DEPARTMENT Section */}
          {isEngineeringActive && (
            <>
              <div className="px-1 pt-4 pb-1">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: '#6366f1' }}>Engineering & IT Ops</span>
              </div>
              {ENGINEERING_NAV.map(n => (
                <SidebarNavLink key={n.path} item={n} colors={colors} />
              ))}
            </>
          )}


          {/* PLATFORM Section */}
          <div className="px-1 pt-4 pb-1">
            <button onClick={() => setPlatformCollapsed(!platformCollapsed)}
              className="flex items-center gap-1 w-full text-left">
              <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: colors.inkSubtle }}>Platform</span>
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
              <span className="text-[10px]" style={{ color: colors.inkTertiary }}>{user?.role || 'VIEWER'}</span>
            </div>
            <button onClick={logout} title="Sign out" className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Area */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* Top Bar */}
        <header className="h-14 flex items-center justify-between px-6 border-b flex-shrink-0 z-10" style={{ borderColor: colors.hairline, background: colors.surface1 }}>
          <div className="flex items-center gap-4">
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
            {/* System Status */}
            <div className="flex items-center gap-2 px-2 py-1 rounded" style={{ background: 'rgba(34, 197, 94, 0.1)' }}>
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-[11px] font-medium text-green-500">System Online</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }} />
              <input
                ref={searchRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => setSearchFocused(true)}
                onBlur={() => setTimeout(() => setSearchFocused(false), 200)}
                placeholder="Search… ⌘K"
                className="pl-8 pr-3 py-1.5 rounded border text-[12px] focus:outline-none focus:ring-1 transition-all"
                style={{
                  background: colors.canvas,
                  borderColor: searchFocused ? colors.primary : colors.hairline,
                  color: colors.ink,
                  width: searchFocused ? '280px' : '200px',
                }}
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2" style={{ color: colors.inkSubtle }}>
                  <X className="w-3 h-3" />
                </button>
              )}
              {/* Search Results Dropdown */}
              {searchFocused && (searchResults.length > 0 || entityResults.length > 0) && (
                <div className="absolute top-full left-0 mt-1 w-full rounded border shadow-lg z-50 overflow-hidden max-h-[420px] overflow-y-auto"
                  style={{ background: colors.surface1, borderColor: colors.hairline }}>
                  {searchResults.length > 0 && (
                    <div className="px-3 pt-2 pb-1 text-[9px] uppercase tracking-wider font-semibold"
                      style={{ color: colors.inkSubtle }}>Go to</div>
                  )}
                  {searchResults.map(r => (
                    <div key={r.path}
                      onMouseDown={() => { navigate(r.path); setSearchQuery(''); }}
                      className="px-3 py-2 text-[13px] cursor-pointer hover:bg-surface2 transition-colors flex items-center gap-2"
                      style={{ color: colors.ink }}>
                      <Search className="w-3 h-3" style={{ color: colors.inkSubtle }} />
                      {r.label}
                    </div>
                  ))}
                  {entityResults.length > 0 && (
                    <div className="px-3 pt-2 pb-1 text-[9px] uppercase tracking-wider font-semibold border-t"
                      style={{ color: colors.inkSubtle, borderColor: colors.hairline }}>In your company brain</div>
                  )}
                  {entityResults.map((r, i) => (
                    <div key={`${r.path}-${i}`}
                      onMouseDown={() => { navigate(r.path); setSearchQuery(''); }}
                      className="px-3 py-2 cursor-pointer hover:bg-surface2 transition-colors"
                      style={{ color: colors.ink }}>
                      <div className="text-[12px] truncate">{r.label}</div>
                      <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{r.sub}</div>
                    </div>
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
            <div className="relative">
              <button onClick={() => setNotifOpen(o => !o)}
                className="p-1.5 rounded hover:bg-surface2 transition-colors relative"
                style={{ color: notifOpen ? colors.primary : colors.inkSubtle }}>
                <Bell className="w-4 h-4" />
                {(notifs.length + orgNotifs.length) > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-1 rounded-full text-[9px] font-bold text-white flex items-center justify-center"
                    style={{ background: colors.error }}>{(notifs.length + orgNotifs.length) > 9 ? '9+' : (notifs.length + orgNotifs.length)}</span>
                )}
              </button>
              {notifOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setNotifOpen(false)} />
                  <div className="absolute top-full right-0 mt-1 w-80 rounded-lg border shadow-xl z-50 overflow-hidden"
                    style={{ background: colors.surface1, borderColor: colors.hairline }}>
                    <div className="px-3 py-2.5 border-b flex items-center justify-between" style={{ borderColor: colors.hairline }}>
                      <span className="text-[12px] font-semibold" style={{ color: colors.ink }}>Notifications</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                        style={{ background: notifs.length ? colors.error + '20' : colors.surface3, color: notifs.length ? colors.error : colors.inkSubtle }}>
                        {notifs.length} pending
                      </span>
                    </div>
                    <div className="max-h-[360px] overflow-y-auto">
                      {/* Org notifications: SLA escalations, @mentions, automation alerts */}
                      {orgNotifs.map(n => (
                        <div key={n.id}
                          onClick={() => { navigate('/pulse'); setNotifOpen(false); }}
                          className="px-3 py-2.5 cursor-pointer hover:bg-surface2 transition-colors border-b"
                          style={{ borderColor: colors.hairline }}>
                          <div className="flex items-start gap-2">
                            <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5"
                              style={{ background: (n.severity === 'critical' ? colors.error : colors.warning) + '20' }}>
                              <Activity className="w-3.5 h-3.5" style={{ color: n.severity === 'critical' ? colors.error : colors.warning }} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{n.title}</div>
                              {n.description && <div className="text-[10px] mt-0.5 truncate" style={{ color: colors.inkSubtle }}>{n.description}</div>}
                            </div>
                          </div>
                        </div>
                      ))}
                      {notifs.length === 0 && orgNotifs.length === 0 ? (
                        <div className="px-3 py-8 text-center">
                          <Bell className="w-6 h-6 mx-auto mb-2" style={{ color: colors.inkTertiary }} />
                          <div className="text-[12px]" style={{ color: colors.inkSubtle }}>You're all caught up</div>
                          <div className="text-[10px] mt-0.5" style={{ color: colors.inkTertiary }}>No decisions or alerts awaiting you</div>
                        </div>
                      ) : notifs.map(n => (
                        <div key={n.id}
                          onClick={() => { navigate('/platform/decisions'); setNotifOpen(false); }}
                          className="px-3 py-2.5 cursor-pointer hover:bg-surface2 transition-colors border-b"
                          style={{ borderColor: colors.hairline }}>
                          <div className="flex items-start gap-2">
                            <div className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5" style={{ background: colors.warning + '20' }}>
                              <Shield className="w-3.5 h-3.5" style={{ color: colors.warning }} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{n.task_intent || n.skill_id_name}</div>
                              <div className="text-[10px] mt-0.5" style={{ color: colors.inkSubtle }}>
                                Approval required{n.route_type ? ` · ${n.route_type === 'GATED_AGENT' ? 'Pipeline gate' : n.route_type}` : ''}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    {notifs.length > 0 && (
                      <div onClick={() => { navigate('/platform/decisions'); setNotifOpen(false); }}
                        className="px-3 py-2 text-center text-[12px] cursor-pointer hover:bg-surface2 transition-colors font-medium"
                        style={{ color: colors.primary }}>
                        Review all in Decisions
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
            {/* Chat Copilot Toggle */}
            <button onClick={() => setChatOpen(!chatOpen)}
              className="p-1.5 rounded hover:bg-surface2 transition-colors relative"
              style={{ color: chatOpen ? colors.primary : colors.inkSubtle }}>
              <MessageSquare className="w-4 h-4" />
            </button>
            <button onClick={toggle} className="p-1.5 rounded hover:bg-surface2 transition-colors" style={{ color: colors.inkSubtle }}>
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
                <Route path="/departments/engineering" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="services" /></ThemeAdapter>} />
                <Route path="/departments/engineering/services" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="services" /></ThemeAdapter>} />
                <Route path="/departments/engineering/pull-requests" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="pull-requests" /></ThemeAdapter>} />
                <Route path="/departments/engineering/deployments" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="deployments" /></ThemeAdapter>} />
                <Route path="/departments/engineering/incidents" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="incidents" /></ThemeAdapter>} />
                <Route path="/departments/engineering/postmortems" element={<ThemeAdapter><EngineeringView domain={domain} defaultTab="postmortems" /></ThemeAdapter>} />

                <Route path="/departments/operations" element={<ThemeAdapter><OperationsDashboard /></ThemeAdapter>} />
                <Route path="/departments/operations/projects" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="projects" /></ThemeAdapter>} />
                <Route path="/departments/operations/resources" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="resources" /></ThemeAdapter>} />
                <Route path="/departments/operations/vendors" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="vendors" /></ThemeAdapter>} />
                <Route path="/departments/operations/procurement" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="procurement" /></ThemeAdapter>} />
                <Route path="/departments/operations/quality" element={<ThemeAdapter><OperationsView domain={domain} defaultTab="quality" /></ThemeAdapter>} />


                {/* DEPARTMENT DETAIL (dynamic) */}
                <Route path="/departments/:deptId" element={<ThemeAdapter><DepartmentDetail domain={domain} /></ThemeAdapter>} />

                {/* PLATFORM */}
                <Route path="/getting-started" element={<ThemeAdapter><GettingStarted /></ThemeAdapter>} />
                <Route path="/platform/foundry" element={<ThemeAdapter><AIFoundry /></ThemeAdapter>} />
                <Route path="/platform/onboarding" element={<ThemeAdapter><ClientOnboarding /></ThemeAdapter>} />
                <Route path="/platform/reality" element={<ThemeAdapter><RealityExperience /></ThemeAdapter>} />
                <Route path="/platform/knowledge" element={<ThemeAdapter><KnowledgeView domain={domain} /></ThemeAdapter>} />
                <Route path="/platform/agents" element={<ThemeAdapter><AgentsView domain={domain} /></ThemeAdapter>} />
                <Route path="/platform/decisions" element={<ThemeAdapter><DecisionsView domain={domain} /></ThemeAdapter>} />
                {/* Company Brain merged into Knowledge; Trust merged into Decisions (Governance tab). */}
                <Route path="/platform/brain" element={<Navigate to="/platform/knowledge" replace />} />
                <Route path="/platform/trust" element={<Navigate to="/platform/decisions" replace />} />
                <Route path="/platform/users" element={<ThemeAdapter><UserManagement /></ThemeAdapter>} />
                <Route path="/platform/settings" element={<ThemeAdapter><SettingsView domain={domain} /></ThemeAdapter>} />

                {/* Fallback */}
                <Route path="*" element={<ThemeAdapter><WorkforceDashboard domain={domain} /></ThemeAdapter>} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </div>

        {/* Chat Copilot Overlay */}
        {chatOpen && (
          <Suspense fallback={null}>
            <ChatCopilot onClose={() => setChatOpen(false)} />
          </Suspense>
        )}
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

  return <Shell />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AuthGuard />
      </AuthProvider>
    </ThemeProvider>
  );
}
