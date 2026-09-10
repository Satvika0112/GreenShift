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
      if (err.response?.status === 401 || err.response?.status === 403) {
        logout();
      }
    } finally {
      setIsLoading(false);
    }
  }, [logout]);

  // Restore authenticated session on initial mount
  useEffect(() => {
    const handleAuthExpired = () => {
      logout();
    };
    window.addEventListener('greenshift:auth-expired', handleAuthExpired);

    if (token) {
      refreshUser();
    } else {
      setIsLoading(false);
    }

    return () => window.removeEventListener('greenshift:auth-expired', handleAuthExpired);
  }, [token, refreshUser, logout]);

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
