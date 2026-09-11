import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { User, UserRole, AuthTokenResponse } from '../types/api';
import { authApi } from '../api/endpoints';

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  hasRole: (roles: UserRole[]) => boolean;
  isAdmin: boolean;
  isPlatformAdmin: boolean;
  isCompanyAdmin: boolean;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => {
    return sessionStorage.getItem('greenshift_token');
  });
  const [user, setUser] = useState<User | null>(() => {
    const saved = sessionStorage.getItem('greenshift_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    sessionStorage.removeItem('greenshift_token');
    sessionStorage.removeItem('greenshift_user');
  }, []);

  const refreshUser = useCallback(async () => {
    const currentToken = sessionStorage.getItem('greenshift_token');
    if (!currentToken) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    try {
      const liveUser = await authApi.getCurrentUser();
      setUser(liveUser);
      sessionStorage.setItem('greenshift_user', JSON.stringify(liveUser));
    } catch (err: any) {
      // Fail closed on every failure, not just 401/403: the `user` object
      // resolved on mount comes from client-editable sessionStorage, and
      // role/tenant/team must only ever be trusted once a real backend
      // response has confirmed it. A network/5xx hiccup leaving that
      // unconfirmed value in place (with isLoading flipped to false) would
      // let role-gated UI render off a value the backend never verified —
      // logging out and requiring re-login is the safe default here.
      logout();
    } finally {
      setIsLoading(false);
    }
  }, [logout]);

  // Restore authenticated session on initial mount only. `login()` already
  // sets `user` directly from the login response, so re-running this on
  // every token change would fire a redundant /auth/me call right after a
  // fresh login and risk clobbering it if that call has any transient hiccup.
  useEffect(() => {
    if (token) {
      refreshUser();
    } else {
      setIsLoading(false);
    }
    // Mount-only: intentionally excludes `token` (see comment above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      logout();
    };
    window.addEventListener('greenshift:auth-expired', handleAuthExpired);
    return () => window.removeEventListener('greenshift:auth-expired', handleAuthExpired);
  }, [logout]);

  // Authenticate user against real backend API. Credentials are the only
  // thing that determines identity/role — there is no client-side default
  // or bypass path here.
  const login = async (username: string, password: string) => {
    setIsLoading(true);
    try {
      const res: AuthTokenResponse = await authApi.login({ username, password });
      setToken(res.access_token);
      sessionStorage.setItem('greenshift_token', res.access_token);

      // The role and team_id strictly come from the authenticated backend user
      const authenticatedUser: User = res.user;
      setUser(authenticatedUser);
      sessionStorage.setItem('greenshift_user', JSON.stringify(authenticatedUser));
    } catch (err) {
      logout();
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const isPlatformAdmin = user?.role === 'PLATFORM_ADMIN';
  const isCompanyAdmin = isPlatformAdmin || user?.role === 'COMPANY_ADMIN';
  const isAdmin = isCompanyAdmin;

  const hasRole = (roles: UserRole[]) => {
    if (!user) return false;
    if (isPlatformAdmin) return true;
    return roles.includes(user.role);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!user && !!token,
        isLoading,
        login,
        logout,
        hasRole,
        isAdmin,
        isPlatformAdmin,
        isCompanyAdmin,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
