/**
 * KAEOS - Finance Dashboard
 * Department-level overview for the Finance domain.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import { BrainLoading } from '../components/BrainStates';
import {
  DollarSign, Briefcase, Landmark, ShieldAlert, Scale,
  BarChart3, Bot, Zap, ArrowRight, TrendingUp, CheckCircle,
  FileSpreadsheet, ClipboardList, Wallet, Receipt
} from 'lucide-react';
import DomainIcon from '../components/DomainIcon';

export default function FinanceDashboard() {
  const { colors } = useTheme();
  const navigate = useNavigate();
  const [dept, setDept] = useState<any>(null);
  const [finStats, setFinStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getWorkforceDepartment('finance').catch(() => null),
      api.getFinanceDashboard().catch(() => null),
    ]).then(([d, f]) => {
      setDept(d);
      setFinStats(f);
      setLoading(false);
    });
  }, []);

  if (loading) return <BrainLoading message="Loading Financial Intelligence..." />;

  const card = {
    background: colors.surface1,
    borderRadius: '12px',
    border: `1px solid ${colors.hairline}`,
    padding: '20px'
  };

  const healthColor = (h: number) => h > 0.8 ? '#22c55e' : h > 0.5 ? '#f59e0b' : '#ef4444';

  if (!dept && !finStats) {
    return (
      <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
        <div className="max-w-7xl mx-auto p-6">
          <div className="flex flex-col items-center justify-center py-20 gap-6" style={card}>
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: '#3b82f615' }}>
              <Landmark className="w-10 h-10" style={{ color: '#3b82f6' }} />
            </div>
            <div className="text-center max-w-md">
              <h2 className="text-[18px] font-bold mb-2">Finance Department Not Deployed</h2>
              <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
                Deploy the Finance & Accounting pack to manage ledgers, billing, expense policies,
                audits, and cash planning with active AI-powered agents.
              </p>
            </div>
            <button onClick={() => navigate('/deploy')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: '#3b82f6' }}>
              Deploy Finance Department <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const quickLinks = [
    { label: 'AP Ledger', path: '/departments/finance/ap', icon: Receipt, color: '#ec4899' },
    { label: 'AR Ledger', path: '/departments/finance/ar', icon: Landmark, color: '#3b82f6' },
    { label: 'Budgets & Forecasts', path: '/departments/finance/budgets', icon: BarChart3, color: '#8b5cf6' },
    { label: 'Expense Reports', path: '/departments/finance/expenses', icon: Wallet, color: '#22c55e' },
    { label: 'Tax Governance', path: '/departments/finance/tax', icon: Scale, color: '#f59e0b' },
    { label: 'Internal Audit', path: '/departments/finance/audit', icon: ShieldAlert, color: '#ef4444' },
  ];

  return (
    <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <DomainIcon hint="finance" size={56} />
            <div>
              <h1 className="text-[24px] font-bold tracking-tight">{dept?.name || 'Finance & Accounting'}</h1>
              <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>
                {dept?.description || 'Autonomous general ledger, cash management, internal audit, and compliance.'}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {dept?.status && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold" style={{ background: '#3b82f620', color: '#3b82f6' }}>
                    {dept.status}
                  </span>
                )}
                {(dept?.compliance_frameworks || []).map((f: string) => (
                  <span key={f} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: '#8b5cf615', color: '#8b5cf6' }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {dept && (
            <div className="flex items-center gap-2">
              <span className="text-[12px]" style={{ color: colors.inkSubtle }}>Department Health:</span>
              <span className="text-[20px] font-bold" style={{ color: healthColor(dept.health_score || 0) }}>
                {Math.round((dept.health_score || 0) * 100)}%
              </span>
            </div>
          )}
        </div>

        {/* Operational Indicators */}
        <div className="grid grid-cols-6 gap-3">
          {[
            { label: 'Cash Balance', value: finStats ? `$${(finStats.total_cash_position / 1000).toFixed(0)}k` : '-', icon: Wallet, color: '#22c55e' },
            { label: 'Accounts Payable', value: finStats ? `$${(finStats.accounts_payable?.total_outstanding / 1000).toFixed(0)}k` : '-', icon: Receipt, color: '#ec4899' },
            { label: 'Accounts Receivable', value: finStats ? `$${(finStats.accounts_receivable?.total_outstanding / 1000).toFixed(0)}k` : '-', icon: Landmark, color: '#3b82f6' },
            { label: 'Net Working Capital', value: finStats ? `$${(finStats.net_working_capital / 1000).toFixed(0)}k` : '-', icon: DollarSign, color: '#8b5cf6' },
            { label: 'Active Budgets', value: finStats?.active_budgets ?? 0, icon: BarChart3, color: '#f59e0b' },
            { label: 'Open Audit Issues', value: finStats?.open_audit_findings ?? 0, icon: ShieldAlert, color: '#ef4444' },
          ].map(kpi => (
            <div key={kpi.label} className="p-3 rounded-xl text-center" style={{ background: kpi.color + '08', border: `1px solid ${kpi.color}12` }}>
              <kpi.icon className="w-5 h-5 mx-auto mb-1" style={{ color: kpi.color }} />
              <div className="text-[16px] font-bold" style={{ color: kpi.color }}>{kpi.value}</div>
              <div className="text-[9px] uppercase tracking-wider font-semibold" style={{ color: colors.inkSubtle }}>{kpi.label}</div>
            </div>
          ))}
        </div>

        {/* Sub-modules navigation */}
        <div className="grid grid-cols-3 gap-4">
          {quickLinks.map(link => (
            <button key={link.label} onClick={() => navigate(link.path)}
              className="flex items-center gap-3 p-4 rounded-xl text-left transition-all hover:shadow-sm group"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: link.color + '15' }}>
                <link.icon className="w-5 h-5" style={{ color: link.color }} />
              </div>
              <div className="flex-1">
                <div className="text-[13px] font-semibold group-hover:text-primary transition-colors">{link.label}</div>
                <div className="text-[10px]" style={{ color: colors.inkSubtle }}>Explore ledger & workflows →</div>
              </div>
              <ArrowRight className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: colors.primary }} />
            </button>
          ))}
        </div>

        {/* Bottom Section: Left (Capabilities/Agents) | Right (Balance details) */}
        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2 space-y-6">
            {/* Capabilities */}
            {(dept?.capabilities || []).length > 0 && (
              <div style={card}>
                <h3 className="text-[14px] font-bold mb-4 flex items-center gap-1.5">
                  <Zap className="w-4 h-4 text-amber-500" /> Finance Capabilities
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {dept.capabilities.map((cap: any) => (
                    <div key={cap.id} className="p-3 rounded-lg" style={{ background: colors.canvas, border: `1px solid ${colors.hairline}` }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[12px] font-semibold flex items-center gap-1.5">
                          <DomainIcon hint={cap.icon || cap.name} fallbackHint={cap.name} size={24} /> {cap.name}
                        </span>
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: cap.status === 'ACTIVE' ? '#22c55e20' : '#f59e0b20', color: cap.status === 'ACTIVE' ? '#22c55e' : '#f59e0b' }}>
                          {cap.status}
                        </span>
                      </div>
                      <p className="text-[11px]" style={{ color: colors.inkSubtle }}>{cap.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div style={card} className="space-y-4">
            <h3 className="text-[14px] font-bold flex items-center gap-1.5">
              <Bot className="w-4 h-4" style={{ color: colors.primary }} /> Active Finance Agents
            </h3>
            <div className="space-y-3">
              {(dept?.agent_definitions || []).length === 0 && (
                <p className="text-[11px]" style={{ color: colors.inkSubtle }}>No agents deployed yet.</p>
              )}
              {(dept?.agent_definitions || []).map((agent: any) => (
                <div key={agent.name} className="flex items-center justify-between p-2.5 rounded-lg border" style={{ borderColor: colors.hairline, background: colors.canvas }}>
                  <div className="flex items-center gap-2">
                    <span className="text-[16px]">{agent.icon}</span>
                    <div>
                      <div className="text-[12px] font-bold">{agent.name}</div>
                      <div className="text-[10px]" style={{ color: colors.inkSubtle }}>{agent.role}</div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-green-500/10 text-green-500">Active</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
