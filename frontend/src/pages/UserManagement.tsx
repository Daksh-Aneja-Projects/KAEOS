import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { api, downloadFile } from '../api/client';
import {
  UserPlus, Shield, Eye, Trash2, XCircle,
  Loader2, Crown, BarChart3, Info, Download
} from 'lucide-react';
import { DEPARTMENTS, DEPARTMENT_LABELS, DEPARTMENT_COLORS } from '../lib/departments';
import { humanize } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import { TableCard } from '../components/shared/TableCard';

interface UserRecord {
  id: string;
  email: string;
  display_name: string;
  role: 'ADMIN' | 'ANALYST' | 'VIEWER';
  department?: string | null;
  is_active: boolean;
  is_demo: boolean;
  login_count: number;
  last_login_at: string | null;
  created_at: string | null;
}


export default function UserManagement() {
  const { colors } = useTheme();
  const { isAdmin, user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editingRole, setEditingRole] = useState<string | null>(null);
  const [editingDept, setEditingDept] = useState<string | null>(null);
  // "Scope applies from next login" hint shown after a department change.
  const [deptNotice, setDeptNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Create form
  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<'ADMIN' | 'ANALYST' | 'VIEWER'>('VIEWER');
  const [newDepartment, setNewDepartment] = useState<string>(''); // '' = Org-wide
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);
  // Access-review export (GET /auth/users/export.csv)
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportAccessReview = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await downloadFile(api.usersCsvPath(), 'access_review.csv');
    } catch (e: any) {
      setExportError(e?.message || 'Export failed.');
    } finally {
      setExporting(false);
    }
  };

  const fetchUsers = async () => {
    try {
      const data = await api.authUsers();
      setUsers(data);
      setFetchError(null);
    } catch (err: any) {
      console.error('[UserManagement] fetch failed:', err);
      setFetchError(err?.message || 'Failed to load users');
    }
    setLoading(false);
  };

  useEffect(() => { fetchUsers(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError('');
    setCreating(true);
    try {
      const created = await api.authCreateUser({ email: newEmail, display_name: newName, password: newPassword, role: newRole });
      // POST /auth/users has no department field; scope the new account with
      // the dedicated endpoint right after creation.
      if (newDepartment && created?.id) {
        const res = await api.updateUserDepartment(created.id, newDepartment);
        showDeptNotice(res?.note);
      }
      setShowCreate(false);
      setNewEmail(''); setNewName(''); setNewPassword(''); setNewRole('VIEWER'); setNewDepartment('');
      fetchUsers();
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create user');
    }
    setCreating(false);
  };

  const handleRoleChange = async (userId: string, role: string) => {
    try {
      await api.authUpdateRole(userId, role);
      setEditingRole(null);
      fetchUsers();
    } catch (err: any) {
      setEditingRole(null);
      showActionError(err?.message || 'Role update failed. Please retry.');
    }
  };

  const showDeptNotice = (note?: string) => {
    setDeptNotice(note || "Scope applies from the user's next login.");
    window.setTimeout(() => setDeptNotice(null), 8000);
  };

  const showActionError = (msg: string) => {
    setActionError(msg);
    window.setTimeout(() => setActionError(null), 8000);
  };

  const handleDepartmentChange = async (userId: string, department: string | null) => {
    try {
      const res = await api.updateUserDepartment(userId, department);
      setEditingDept(null);
      showDeptNotice(res?.note);
      fetchUsers();
    } catch (err: any) {
      setEditingDept(null);
      showActionError(err?.message || 'Department update failed. Please retry.');
    }
  };

  const deptLabel = (d: string) => (DEPARTMENT_LABELS as Record<string, string>)[d] || d;
  const deptColor = (d: string) => (DEPARTMENT_COLORS as Record<string, string>)[d] || '#6366f1';
  const deptShort = (d: string) => d === 'hr' ? 'HR' : d.charAt(0).toUpperCase() + d.slice(1);

  const handleDeactivate = async (userId: string) => {
    if (!confirm('Deactivate this user?')) return;
    try {
      await api.authDeleteUser(userId);
      fetchUsers();
    } catch (err) { console.error('[UserManagement] deactivate failed:', err); }
  };

  const roleIcon = (r: string) => r === 'ADMIN' ? Crown : r === 'ANALYST' ? BarChart3 : Eye;
  const roleColor = (r: string) => r === 'ADMIN' ? '#8b5cf6' : r === 'ANALYST' ? '#3b82f6' : '#22c55e';

  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center p-8">
          <Shield className="w-12 h-12 mx-auto mb-3" style={{ color: colors.inkSubtle }} />
          <h2 className="text-[16px] font-semibold" style={{ color: colors.ink }}>Access Restricted</h2>
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Only administrators can manage accounts.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`${PAGE_PAD} space-y-5`} style={{ color: colors.ink }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight">User Management</h2>
          <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
            {users.length} users • RBAC: Admin / Analyst / Viewer • Department scopes
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={exportAccessReview} disabled={exporting}
            title="Download every account, role, department scope, and last sign-in as a CSV for your access review"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] font-medium disabled:opacity-50"
            style={{ background: colors.surface2, color: colors.inkMuted, border: `1px solid ${colors.hairline}` }}>
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            {exporting ? 'Preparing…' : 'Access Review CSV'}
          </button>
          <button onClick={() => setShowCreate(!showCreate)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white transition-all hover:brightness-110"
            style={{ background: colors.primary }}>
            <UserPlus className="w-4 h-4" /> New User
          </button>
        </div>
      </div>

      {exportError && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-[12px] font-medium"
          style={{ background: '#ef444415', color: '#ef4444' }}>
          <XCircle className="w-4 h-4 shrink-0" />
          <span className="flex-1">{exportError}</span>
          <button onClick={() => setExportError(null)} className="text-[11px] opacity-70">dismiss</button>
        </div>
      )}

      {/* Create User Form */}
      {showCreate && (
        <form onSubmit={handleCreate} className="rounded-xl p-5 space-y-4"
          style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <h3 className="text-[14px] font-semibold">Create New User</h3>
          {createError && (
            <div className="px-3 py-2 rounded-lg text-[12px]" style={{ background: '#ef444415', color: '#ef4444' }}>
              {createError}
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Display Name</label>
              <input value={newName} onChange={e => setNewName(e.target.value)} required
                className="w-full px-3 py-2 rounded-lg border text-[13px]"
                style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                placeholder="Jane Smith" />
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Email</label>
              <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} required
                className="w-full px-3 py-2 rounded-lg border text-[13px]"
                style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                placeholder="jane@company.com" />
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Password</label>
              <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} required minLength={6}
                className="w-full px-3 py-2 rounded-lg border text-[13px]"
                style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}
                placeholder="min 6 characters" />
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Role</label>
              <select value={newRole} onChange={e => setNewRole(e.target.value as any)}
                className="w-full px-3 py-2 rounded-lg border text-[13px]"
                style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                <option value="VIEWER">Viewer - Read only</option>
                <option value="ANALYST">Analyst - Read + Execute</option>
                <option value="ADMIN">Admin - Full access</option>
              </select>
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wider block mb-1" style={{ color: colors.inkSubtle }}>Department</label>
              <select value={newDepartment} onChange={e => setNewDepartment(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-[13px]"
                style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                <option value="">Org-wide - All departments</option>
                {DEPARTMENTS.map(d => (
                  <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
                ))}
              </select>
              <p className="text-[11px] mt-1" style={{ color: colors.inkSubtle }}>
                Scoped users only see their own department's operational pages.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 justify-end">
            <button type="button" onClick={() => setShowCreate(false)}
              className="px-4 py-2 rounded-lg text-[13px] font-medium"
              style={{ color: colors.inkSubtle }}>
              Cancel
            </button>
            <button type="submit" disabled={creating}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white"
              style={{ background: colors.primary }}>
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
              Create User
            </button>
          </div>
        </form>
      )}

      {/* RBAC Legend */}
      <div className="flex items-center gap-4 flex-wrap">
        {[
          { role: 'ADMIN', desc: 'Full access + user mgmt' },
          { role: 'ANALYST', desc: 'Read + execute agents' },
          { role: 'VIEWER', desc: 'Read-only dashboards' },
        ].map(r => (
          <div key={r.role} className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ background: roleColor(r.role) + '10', border: `1px solid ${roleColor(r.role)}20` }}>
            {React.createElement(roleIcon(r.role), { className: 'w-3.5 h-3.5', style: { color: roleColor(r.role) } })}
            <span className="text-[11px] font-semibold" style={{ color: roleColor(r.role) }}>{humanize(r.role)}</span>
            <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{r.desc}</span>
          </div>
        ))}
      </div>

      {/* Department scope change hint */}
      {deptNotice && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-[12px]"
          style={{ background: colors.primary + '12', color: colors.primary, border: `1px solid ${colors.primary}30` }}>
          <Info className="w-3.5 h-3.5 shrink-0" />
          <span>{deptNotice}</span>
        </div>
      )}
      {actionError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-[12px]"
          style={{ background: '#ef444412', color: '#ef4444', border: '1px solid #ef444430' }}>
          <XCircle className="w-3.5 h-3.5 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}

      {/* User Table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
        </div>
      ) : fetchError && users.length === 0 ? (
        <div className="rounded-xl border p-8 text-center" style={{ borderColor: colors.hairline }}>
          <p className="text-[13px] font-medium" style={{ color: colors.error }}>{fetchError}</p>
          <button onClick={() => { setLoading(true); fetchUsers(); }}
            className="mt-3 px-4 py-2 rounded-lg text-[12px] font-semibold"
            style={{ background: colors.surface2, color: colors.ink, border: `1px solid ${colors.hairline}` }}>
            Retry
          </button>
        </div>
      ) : (
        <TableCard minWidth={880}>
          <div className="grid grid-cols-12 text-[11px] font-semibold uppercase tracking-wider px-5 py-3"
            style={{ background: colors.surface1, color: colors.inkSubtle }}>
            <div className="col-span-2">User</div>
            <div className="col-span-3">Email</div>
            <div className="col-span-2 text-center">Role</div>
            <div className="col-span-2 text-center">Department</div>
            <div className="col-span-1 text-center">Logins</div>
            <div className="col-span-1">Last Login</div>
            <div className="col-span-1 text-center">Actions</div>
          </div>
          {users.map(u => {
            const RIcon = roleIcon(u.role);
            return (
              <div key={u.id} className="grid grid-cols-12 items-center px-5 py-3 text-[13px]"
                style={{ borderTop: `1px solid ${colors.hairline}`, opacity: u.is_active ? 1 : 0.5 }}>
                <div className="col-span-2 flex items-center gap-2.5 min-w-0">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center text-[12px] font-bold shrink-0"
                    style={{ background: roleColor(u.role) + '15', color: roleColor(u.role) }}>
                    {u.display_name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div className="font-medium truncate" title={u.display_name}>{u.display_name}</div>
                    {u.is_demo && <span className="text-[11px] px-1.5 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>Demo account</span>}
                  </div>
                </div>
                <div className="col-span-3 text-[12px] truncate pr-2" title={u.email} style={{ color: colors.inkSubtle }}>{u.email}</div>
                <div className="col-span-2 text-center relative">
                  {editingRole === u.id ? (
                    <select value={u.role} onChange={e => handleRoleChange(u.id, e.target.value)}
                      onBlur={() => setEditingRole(null)} autoFocus
                      className="px-2 py-1 rounded border text-[11px]"
                      style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                      <option value="ADMIN">Admin</option>
                      <option value="ANALYST">Analyst</option>
                      <option value="VIEWER">Viewer</option>
                    </select>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-bold cursor-pointer"
                      onClick={() => !u.is_demo && setEditingRole(u.id)}
                      style={{ background: roleColor(u.role) + '15', color: roleColor(u.role) }}>
                      <RIcon className="w-3 h-3" /> {humanize(u.role)}
                    </span>
                  )}
                </div>
                <div className="col-span-2 text-center">
                  {editingDept === u.id ? (
                    <select value={u.department || ''}
                      onChange={e => handleDepartmentChange(u.id, e.target.value || null)}
                      onBlur={() => setEditingDept(null)} autoFocus
                      className="px-2 py-1 rounded border text-[11px] max-w-full"
                      style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                      <option value="">Org-wide</option>
                      {DEPARTMENTS.map(d => (
                        <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
                      ))}
                    </select>
                  ) : u.department ? (
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-[11px] font-bold cursor-pointer"
                      onClick={() => setEditingDept(u.id)}
                      title={`Scoped to ${deptLabel(u.department)}. Click to change.`}
                      style={{ background: deptColor(u.department) + '15', color: deptColor(u.department) }}>
                      {deptShort(u.department)}
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-[11px] font-medium cursor-pointer"
                      onClick={() => setEditingDept(u.id)}
                      title="Org-wide access. Click to scope to a department."
                      style={{ color: colors.inkSubtle, background: colors.surface2 }}>
                      Org-wide
                    </span>
                  )}
                </div>
                <div className="col-span-1 text-center font-mono text-[12px]">{u.login_count || 0}</div>
                <div className="col-span-1 text-[11px] truncate whitespace-nowrap" title={u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never logged in'} style={{ color: colors.inkSubtle }}>
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : 'Never'}
                </div>
                <div className="col-span-1 text-center">
                  {!u.is_demo && u.id !== currentUser?.id && (
                    <button onClick={() => handleDeactivate(u.id)}
                      className="p-1.5 rounded hover:bg-surface2 transition-colors"
                      style={{ color: '#ef4444' }}
                      aria-label={`Deactivate ${u.display_name}`} title="Deactivate">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </TableCard>
      )}
    </div>
  );
}
