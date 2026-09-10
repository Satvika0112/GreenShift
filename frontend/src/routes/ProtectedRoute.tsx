import React from 'react';
import { Navigate, Outlet, useNavigate } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { UserRole } from '../types/api';
import { EmptyState } from '../components/common/EmptyState';

interface ProtectedRouteProps {
  allowedRoles?: UserRole[];
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ allowedRoles }) => {
  const { isAuthenticated, isLoading, hasRole } = useAuth();
  const navigate = useNavigate();

  // A token can exist in storage while the authenticated user is still being
  // fetched from the backend (page refresh, tab reopen). Without this guard,
  // isAuthenticated is briefly false and this component would redirect an
  // already-logged-in user to /login before their session finishes resolving.
  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          color: 'var(--text-muted)',
          fontSize: '0.85rem',
        }}
      >
        Resolving session…
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // The user is authenticated but their backend-assigned role doesn't allow
  // this route. This is a 403-shaped case: they stay signed in, and get a
  // clear way back rather than being bounced to /login.
  if (allowedRoles && !hasRole(allowedRoles)) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Access Denied"
        description="You're signed in, but your account doesn't have permission to view this page."
        action={{ label: 'Back to Dashboard', onClick: () => navigate('/') }}
      />
    );
  }

  return <Outlet />;
};
