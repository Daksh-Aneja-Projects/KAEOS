import React, { useEffect, useState } from 'react';
import type { RedTeamScan } from '../api/client';
import { api } from '../api/client';
import { Shield, AlertTriangle, CheckCircle, XCircle, Play } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { BrainLoading, BrainEmpty, BrainError } from '../components/BrainStates';

const RedTeamDashboard = () => {
 const { colors } = useTheme();
 const [scans, setScans] = useState<RedTeamScan[]>([]);
 const [summary, setSummary] = useState<any>(null);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState<string | null>(null);
 const [scanning, setScanning] = useState<string | null>(null);

 const load = () => {
  setError(null);
  api.getRecentScans().then(d => { setScans(d.scans); setSummary(d.summary); setLoading(false); }).catch((e: any) => { setError(e?.message || 'Failed to load red team scans'); setLoading(false); });
 };
 useEffect(load, []);

 const handleScan = async (skillId: string) => {
  setScanning(skillId);
  await api.runScan(skillId);
  setScanning(null);
  load();
 };

 const statusColor = (s: string) => s === 'PASSED' ? colors.success : s === 'WARNING' ? colors.warning : colors.error;
 const statusIcon = (s: string) => s === 'PASSED'
  ? <CheckCircle className="w-4 h-4" style={{ color: colors.success }} />
  : s === 'WARNING'
   ? <AlertTriangle className="w-4 h-4" style={{ color: colors.warning }} />
   : <XCircle className="w-4 h-4" style={{ color: colors.error }} />;

 if (loading) return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <BrainLoading message="Loading red team scans…" />
  </div>
 );
 if (error) return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <BrainError message={error} onRetry={load} />
  </div>
 );

 return (
  <div className="h-full overflow-y-auto" style={{ background: colors.canvas, color: colors.ink }}>
   <div className="max-w-7xl mx-auto p-6 space-y-5">
    {/* Header */}
    <div className="flex items-start justify-between gap-4 flex-wrap pb-5" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
     <div className="flex items-start gap-3">
      <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
       style={{ background: `linear-gradient(135deg, ${colors.primary}, ${colors.primary}99)` }}>
       <Shield className="w-6 h-6 text-white" />
      </div>
      <div>
       <h1 className="text-[24px] font-bold tracking-tight">Red Team Harness</h1>
       <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Adversarial testing and KB vulnerability scanner</p>
      </div>
     </div>
     {summary && (
      <div className="flex gap-3">
       <div className="px-4 py-2 rounded-xl" style={{ background: colors.surface2, border: `1px solid ${colors.hairline}` }}>
        <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.inkSubtle }}>Skills Scanned</div>
        <div className="text-xl font-bold tabular-nums">{summary.total_skills_scanned}</div>
       </div>
       {(() => {
        const vuln = summary.total_vulnerabilities > 0;
        const c = vuln ? colors.error : colors.success;
        return (
         <div className="px-4 py-2 rounded-xl" style={{ background: c + '14', border: `1px solid ${c}33` }}>
          <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: c }}>Vulnerabilities</div>
          <div className="text-xl font-bold tabular-nums" style={{ color: c }}>{summary.total_vulnerabilities}</div>
         </div>
        );
       })()}
      </div>
     )}
    </div>

    {scans.length === 0 ? (
     <BrainEmpty title="No scans yet" action="Run an adversarial scan on a skill to surface vulnerabilities." icon={Shield} />
    ) : (
     <div className="space-y-4">
      {scans.map(scan => (
       <div key={scan.skill_id} className="p-5" style={{ background: colors.surface1, border: `1px solid ${statusColor(scan.status)}55`, borderRadius: '14px' }}>
        <div className="flex items-center justify-between mb-3">
         <div className="flex items-center gap-3">
          {statusIcon(scan.status)}
          <div>
           <h3 className="font-semibold" style={{ color: colors.ink }}>{scan.skill_id}</h3>
           <span className="text-xs" style={{ color: colors.inkSubtle }}>{scan.department} · {scan.scan_count} tests · Last: {scan.last_scan ? new Date(scan.last_scan).toLocaleString() : 'Never'}</span>
          </div>
         </div>
         <div className="flex items-center gap-3">
          {scan.vulnerabilities > 0 && <span className="text-xs px-2 py-0.5 rounded" style={{ color: colors.error, background: colors.error + '1a', border: `1px solid ${colors.error}33` }}>{scan.vulnerabilities} vulns</span>}
          <button onClick={() => handleScan(scan.skill_id)} disabled={scanning === scan.skill_id}
           className="px-3 py-1.5 rounded-xl text-xs font-medium transition-all hover:opacity-90 disabled:opacity-50 flex items-center gap-1"
           style={{ background: colors.primary, color: '#fff' }}
          ><Play className="w-3 h-3" />{scanning === scan.skill_id ? 'Scanning…' : 'Re-scan'}</button>
         </div>
        </div>
        <div className="flex flex-wrap gap-2">
         {scan.details.map((d, i) => {
          const c = statusColor(d.status);
          return (
           <div key={i} className="px-3 py-1.5 rounded-xl text-xs" style={{ background: c + '14', border: `1px solid ${c}33`, color: c }}>
            {d.scan_type} · {d.status} {d.vulnerabilities > 0 && `(${d.vulnerabilities})`}
           </div>
          );
         })}
        </div>
       </div>
      ))}
     </div>
    )}
   </div>
  </div>
 );
};

export default RedTeamDashboard;
