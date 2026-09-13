import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { ProtectedRoute } from './ProtectedRoute';

let mockIsAuthenticated: boolean;
let mockIsLoading: boolean;
let mockHasRole: (roles: string[]) => boolean;
const mockLogout = vi.fn();

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated,
    isLoading: mockIsLoading,
    hasRole: mockHasRole,
    logout: mockLogout,
  }),
}));

function renderProtected(allowedRoles?: any[], initialPath = '/protected') {
  const LoginLanding = () => {
    const location = useLocation();
    const from = (location.state as any)?.from?.pathname;
    return (
      <div data-testid="login-landing">
        Login
        {from && <span data-testid="redirect-from">{from}</span>}
      </div>
    );
  };
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<LoginLanding />} />
        <Route path="/" element={<div data-testid="dashboard-landing">Dashboard</div>} />
        <Route element={<ProtectedRoute allowedRoles={allowedRoles} />}>
          <Route path="/protected" element={<div data-testid="protected-content">Secret</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsAuthenticated = false;
    mockIsLoading = false;
    mockHasRole = () => true;
  });

  it('redirects an unauthenticated user to /login', () => {
    renderProtected();
    expect(screen.getByTestId('login-landing')).toBeInTheDocument();
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('preserves the originally-requested URL so login can return the user there', () => {
    renderProtected(undefined, '/protected');
    expect(screen.getByTestId('redirect-from')).toHaveTextContent('/protected');
  });

  it('does not render protected content while the auth state is still loading', () => {
    mockIsLoading = true;
    renderProtected();
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-landing')).not.toBeInTheDocument();
  });

  it('renders protected content for an authenticated user', () => {
    mockIsAuthenticated = true;
    renderProtected();
    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
  });

  it('shows Access Denied (not a redirect to Login, not a logout) when the role does not match', () => {
    mockIsAuthenticated = true;
    mockHasRole = () => false;
    renderProtected(['PLATFORM_ADMIN']);

    expect(screen.getByText('Access Denied')).toBeInTheDocument();
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-landing')).not.toBeInTheDocument();
    expect(mockLogout).not.toHaveBeenCalled();
  });

  it('provides a safe way back from Access Denied', async () => {
    mockIsAuthenticated = true;
    mockHasRole = () => false;
    renderProtected(['PLATFORM_ADMIN']);

    const backButton = screen.getByRole('button', { name: /Back to Dashboard/i });
    expect(backButton).toBeInTheDocument();
  });
});
