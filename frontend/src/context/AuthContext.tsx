import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';

interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: 'ADMIN' | 'ANALYST' | 'VIEWER';
  tenant_id: string;
  is_demo: boolean;
}

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => void;
  isAdmin: boolean;
  isAnalyst: boolean;
  canExecute: boolean; // ADMIN or ANALYST
}

const AuthContext = createContext<AuthContextType>({
  user: null, token: null, loading: true,
  login: async () => ({ ok: false }),
  logout: () => {},
  isAdmin: false, isAnalyst: false, canExecute: false,
});

export const useAuth = () => useContext(AuthContext);


export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('kaeos-token'));
  const [loading, setLoading] = useState(true);

  // Validate token on mount
  useEffect(() => {
    if (!token) { setLoading(false); return; }
    api.authMe()
      .then(u => { setUser(u); setLoading(false); })
      .catch(() => { setToken(null); localStorage.removeItem('kaeos-token'); setLoading(false); });
  }, [token]);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const data = await api.authLogin({ email, password });
      setToken(data.token);
      setUser(data.user);
      localStorage.setItem('kaeos-token', data.token);
      return { ok: true };
    } catch (err: any) {
      return { ok: false, error: err.message || 'Network error' };
    }
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('kaeos-token');
  }, []);

  return (
    <AuthContext.Provider value={{
      user, token, loading, login, logout,
      isAdmin: user?.role === 'ADMIN',
      isAnalyst: user?.role === 'ANALYST',
      canExecute: user?.role === 'ADMIN' || user?.role === 'ANALYST',
    }}>
      {children}
    </AuthContext.Provider>
  );
};
