import React, { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import {
  UserPlus, Shield, Eye, Pencil, Trash2, CheckCircle, XCircle,
  Loader2, Users, Crown, BarChart3, ChevronDown
} from 'lucide-react';

interface UserRecord {
  id: string;
  email: string;
  display_name: string;
  role: 'ADMIN' | 'ANALYST' | 'VIEWER';
  is_active: boolean;
  is_demo: boolean;
  login_count: number;
  last_login_at: string | null;
  created_at: string | null;
}


export default function UserManagement() {
  const { colors } = useTheme();
  const { token, isAdmin, user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editingRole, setEditingRole] = useState<string | null>(null);

  // Create form
  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<'ADMIN' | 'ANALYST' | 'VIEWER'>('VIEWER');
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);

  const headers = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchUsers = async () => {
    try {
      const data = await api.authUsers();
      setUsers(data);
    } catch (err) { console.error('[UserManagement] fetch failed:', err); }
    setLoading(false);
  };

  useEffect(() => { fetchUsers(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError('');
    setCreating(true);
    try {
      await api.authCreateUser({ email: newEmail, display_name: newName, password: newPassword, role: newRole });
      setShowCreate(false);
      setNewEmail(''); setNewName(''); setNewPassword(''); setNewRole('VIEWER');
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
    } catch (err) { console.error('[UserManagement] role update failed:', err); }
  };

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
          <p className="text-[13px] mt-1" style={{ color: colors.inkSubtle }}>Only ADMIN users can manage accounts.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 max-w-7xl mx-auto" style={{ color: colors.ink }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight">User Management</h2>
          <p className="text-[13px]" style={{ color: colors.inkSubtle }}>
            {users.length} users • RBAC: Admin / Analyst / Viewer
          </p>
        </div>
        <button onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-semibold text-white transition-all hover:brightness-110"
          style={{ background: colors.primary }}>
          <UserPlus className="w-4 h-4" /> New User
        </button>
      </div>

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
      <div className="flex items-center gap-4">
        {[
          { role: 'ADMIN', desc: 'Full access + user mgmt' },
          { role: 'ANALYST', desc: 'Read + execute agents' },
          { role: 'VIEWER', desc: 'Read-only dashboards' },
        ].map(r => (
          <div key={r.role} className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ background: roleColor(r.role) + '10', border: `1px solid ${roleColor(r.role)}20` }}>
            {React.createElement(roleIcon(r.role), { className: 'w-3.5 h-3.5', style: { color: roleColor(r.role) } })}
            <span className="text-[11px] font-semibold" style={{ color: roleColor(r.role) }}>{r.role}</span>
            <span className="text-[10px]" style={{ color: colors.inkSubtle }}>{r.desc}</span>
          </div>
        ))}
      </div>

      {/* User Table */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin" style={{ color: colors.primary }} />
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: colors.hairline }}>
          <div className="grid grid-cols-12 text-[10px] font-semibold uppercase tracking-wider px-5 py-3"
            style={{ background: colors.surface1, color: colors.inkSubtle }}>
            <div className="col-span-3">User</div>
            <div className="col-span-3">Email</div>
            <div className="col-span-2 text-center">Role</div>
            <div className="col-span-1 text-center">Logins</div>
            <div className="col-span-2">Last Login</div>
            <div className="col-span-1 text-center">Actions</div>
          </div>
          {users.map(u => {
            const RIcon = roleIcon(u.role);
            return (
              <div key={u.id} className="grid grid-cols-12 items-center px-5 py-3 text-[13px]"
                style={{ borderTop: `1px solid ${colors.hairline}`, opacity: u.is_active ? 1 : 0.5 }}>
                <div className="col-span-3 flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center text-[12px] font-bold"
                    style={{ background: roleColor(u.role) + '15', color: roleColor(u.role) }}>
                    {u.display_name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div className="font-medium">{u.display_name}</div>
                    {u.is_demo && <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>DEMO</span>}
                  </div>
                </div>
                <div className="col-span-3 text-[12px]" style={{ color: colors.inkSubtle }}>{u.email}</div>
                <div className="col-span-2 text-center relative">
                  {editingRole === u.id ? (
                    <select value={u.role} onChange={e => handleRoleChange(u.id, e.target.value)}
                      onBlur={() => setEditingRole(null)} autoFocus
                      className="px-2 py-1 rounded border text-[11px]"
                      style={{ background: colors.canvas, borderColor: colors.hairline, color: colors.ink }}>
                      <option value="ADMIN">ADMIN</option>
                      <option value="ANALYST">ANALYST</option>
                      <option value="VIEWER">VIEWER</option>
                    </select>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold cursor-pointer"
                      onClick={() => !u.is_demo && setEditingRole(u.id)}
                      style={{ background: roleColor(u.role) + '15', color: roleColor(u.role) }}>
                      <RIcon className="w-3 h-3" /> {u.role}
                    </span>
                  )}
                </div>
                <div className="col-span-1 text-center font-mono text-[12px]">{u.login_count || 0}</div>
                <div className="col-span-2 text-[11px]" style={{ color: colors.inkSubtle }}>
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : 'Never'}
                </div>
                <div className="col-span-1 text-center">
                  {!u.is_demo && u.id !== currentUser?.id && (
                    <button onClick={() => handleDeactivate(u.id)}
                      className="p-1.5 rounded hover:bg-surface2 transition-colors"
                      style={{ color: '#ef4444' }} title="Deactivate">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
