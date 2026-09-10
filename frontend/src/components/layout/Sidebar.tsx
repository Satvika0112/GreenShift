import React from 'react';
import { NavLink } from 'react-router-dom';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import {
  LayoutDashboard,
  Layers,
  PlusCircle,
  Cpu,
  CheckCircle2,
  Activity,
  Globe,
  Zap,
  TrendingUp,
  ShieldCheck,
  AlertTriangle,
  Server,
  Users,
  Settings,
  Leaf,
  ChevronRight,
  Shield,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  badge?: number;
  badgeVariant?: 'warning' | 'default';
}

interface NavSection {
  title: string;
  adminOnly?: boolean;
  items: NavItem[];
}

interface SidebarProps {
  pendingApprovalsCount?: number;
  activeJobsCount?: number;
  isMobileOpen?: boolean;
  onNavigate?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  pendingApprovalsCount = 0,
  activeJobsCount = 0,
  isMobileOpen = false,
  onNavigate,
}) => {
  const { user, isAdmin } = useAuth();
  const isNarrow = useMediaQuery('(max-width: 900px)');

  const navSections: NavSection[] = [
    {
      title: 'ORCHESTRATION',
      items: [
        { to: '/', label: 'Overview', icon: LayoutDashboard },
        { to: '/workloads', label: 'Workloads', icon: Layers, badge: activeJobsCount > 0 ? activeJobsCount : undefined },
        { to: '/submit', label: 'Submit Job', icon: PlusCircle },
        { to: '/scheduling', label: 'Scheduling Engine', icon: Cpu },
        {
          to: '/approvals',
          label: 'Approvals',
          icon: CheckCircle2,
          badge: pendingApprovalsCount > 0 ? pendingApprovalsCount : undefined,
          badgeVariant: 'warning',
        },
      ],
    },
    {
      title: 'EXECUTION & GRID',
      items: [
        { to: '/monitoring', label: 'Kubernetes & Jobs', icon: Activity },
        { to: '/regions', label: 'Regions & Capacity', icon: Globe },
        { to: '/carbon-cost', label: 'Carbon & Tariffs', icon: Zap },
      ],
    },
    {
      title: 'GOVERNANCE & TRUST',
      items: [
        { to: '/impact', label: 'Impact Reports', icon: TrendingUp },
        { to: '/audit', label: 'Audit & Trust Chain', icon: ShieldCheck },
        { to: '/alerts', label: 'Notifications', icon: AlertTriangle },
      ],
    },
    {
      title: 'PLATFORM ADMIN',
      adminOnly: true,
      items: [
        { to: '/health', label: 'System Health', icon: Server },
        { to: '/users', label: 'Users & RBAC', icon: Users },
      ],
    },
    {
      title: 'ACCOUNT',
      items: [
        { to: '/settings', label: 'Settings', icon: Settings },
      ],
    },
  ];

  return (
    <aside
      aria-label="Control Plane Sidebar"
      style={{
        width: 'var(--sidebar-width)',
        minWidth: 'var(--sidebar-width)',
        height: '100vh',
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        position: isNarrow ? 'fixed' : 'sticky',
        top: 0,
        left: 0,
        zIndex: 100,
        userSelect: 'none',
        transform: isNarrow && !isMobileOpen ? 'translateX(-100%)' : 'translateX(0)',
        transition: isNarrow ? 'transform 0.22s ease' : undefined,
        boxShadow: isNarrow && isMobileOpen ? 'var(--shadow-lg)' : undefined,
      }}
    >
      {/* Brand Header */}
      <div
        style={{
          height: 'var(--header-height)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 1.25rem',
          gap: '0.75rem',
          borderBottom: '1px solid var(--border-subtle)',
          background: 'rgba(10, 15, 26, 0.6)',
        }}
      >
        <div
          style={{
            width: '34px',
            height: '34px',
            borderRadius: 'var(--radius-sm)',
            background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(6, 182, 212, 0.2))',
            border: '1px solid rgba(16, 185, 129, 0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#10b981',
          }}
        >
          <Leaf size={20} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '1rem', fontWeight: 800, letterSpacing: '-0.02em', color: '#ffffff' }}>
            Green<span style={{ color: '#10b981' }}>Shift</span>
          </span>
          <span style={{ fontSize: '0.65rem', fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
            CONTROL PLANE
          </span>
        </div>
      </div>

      {/* Team Isolation Scope Card */}
      <div style={{ padding: '0.85rem 1.25rem 0.25rem' }}>
        <div
          style={{
            background: 'rgba(255, 255, 255, 0.03)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.6rem 0.75rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <Shield size={13} color="#10b981" />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Team Scope:</span>
          </div>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              color: user?.team_id ? '#38bdf8' : 'var(--text-muted)',
            }}
          >
            {user?.team_id || 'NOT PROVIDED BY BACKEND'}
          </span>
        </div>
      </div>

      {/* Navigation Sections */}
      <nav
        aria-label="Primary Navigation"
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '0.75rem 0.85rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.25rem',
        }}
      >
        {navSections.map((section) => {
          if (section.adminOnly && !isAdmin) return null;

          return (
            <div key={section.title}>
              <div
                style={{
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  color: 'var(--text-muted)',
                  letterSpacing: '0.08em',
                  padding: '0 0.6rem 0.4rem',
                }}
              >
                {section.title}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    onClick={onNavigate}
                    style={({ isActive }) => ({
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.55rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      textDecoration: 'none',
                      fontSize: '0.84rem',
                      fontWeight: isActive ? 600 : 500,
                      color: isActive ? '#ffffff' : 'var(--text-secondary)',
                      background: isActive ? 'linear-gradient(90deg, rgba(16, 185, 129, 0.15), rgba(16, 185, 129, 0.05))' : 'transparent',
                      borderLeft: isActive ? '3px solid #10b981' : '3px solid transparent',
                      transition: 'all 0.15s ease',
                    })}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                      <item.icon size={16} />
                      <span>{item.label}</span>
                    </div>

                    {item.badge !== undefined && (
                      <span
                        style={{
                          fontSize: '0.7rem',
                          fontWeight: 700,
                          padding: '0.1rem 0.45rem',
                          borderRadius: 'var(--radius-full)',
                          background: item.badgeVariant === 'warning' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                          color: item.badgeVariant === 'warning' ? '#f59e0b' : '#10b981',
                          border: item.badgeVariant === 'warning' ? '1px solid rgba(245, 158, 11, 0.3)' : '1px solid rgba(16, 185, 129, 0.3)',
                        }}
                      >
                        {item.badge}
                      </span>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      {/* User Footer with Role Badge */}
      <div
        style={{
          padding: '0.85rem 1.25rem',
          borderTop: '1px solid var(--border-subtle)',
          background: 'rgba(10, 15, 26, 0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <div
            style={{
              width: '28px',
              height: '28px',
              borderRadius: 'var(--radius-full)',
              background: 'linear-gradient(135deg, #10b981, #06b6d4)',
              color: '#090d16',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              fontSize: '0.75rem',
            }}
          >
            {user?.username?.charAt(0).toUpperCase() || 'U'}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {user?.username || '—'}
            </span>
            <span style={{ fontSize: '0.68rem', color: '#10b981', fontWeight: 600 }}>
              {user?.role || '—'}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
