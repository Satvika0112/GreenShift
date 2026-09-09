import React, { useState, useEffect } from 'react';
import {
  Users,
  Shield,
  Key,
  Plus,
  Trash2,
  Copy,
  CheckCircle2,
  XCircle,
  RefreshCw,
  AlertTriangle,
  Building2,
  UserPlus,
  Check,
  X,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { authApi, companyApi } from '../api/endpoints';
import { User, UserRole } from '../types/api';
import { useAuth } from '../context/AuthContext';

export const UsersAccessPage: React.FC = () => {
  const { user, isAdmin, isPlatformAdmin, isCompanyAdmin } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [companies, setCompanies] = useState<any[]>([]);
  const [selectedTenantFilter, setSelectedTenantFilter] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);

  // Key creation state
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [newKeyLabel, setNewKeyLabel] = useState('');
  const [newKeyRole, setNewKeyRole] = useState('OPERATOR');
  const [newKeyTenant, setNewKeyTenant] = useState('');
  const [rawGeneratedKey, setRawGeneratedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // User creation state
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUsername, setNewUsername] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserRole, setNewUserRole] = useState<UserRole>('COMPANY_USER');
  const [newUserTeam, setNewUserTeam] = useState('team-acme');
  const [newUserTenant, setNewUserTenant] = useState('');
  const [isCreatingUser, setIsCreatingUser] = useState(false);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchDirectoryData = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      if (isAdmin) {
        const tenantArg = selectedTenantFilter || undefined;
        const [usersRes, keysRes, compRes] = await Promise.allSettled([
          authApi.getUsers(tenantArg),
          authApi.listApiKeys(tenantArg),
          companyApi.getCompanies(),
        ]);

        if (usersRes.status === 'fulfilled' && Array.isArray(usersRes.value)) {
          setUsers(usersRes.value);
        }
        if (keysRes.status === 'fulfilled' && Array.isArray(keysRes.value)) {
          setApiKeys(keysRes.value);
        }
        if (compRes.status === 'fulfilled' && Array.isArray(compRes.value)) {
          setCompanies(compRes.value);
        }
      } else if (user) {
        setUsers([user]);
      }
    } catch (err: any) {
      setErrorMsg(err.response?.data?.detail || 'Failed to fetch directory data from backend.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDirectoryData();
  }, [user, selectedTenantFilter]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUserEmail.trim() || !newUserPassword) return;
    setIsCreatingUser(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      await authApi.adminCreateUser({
        email: newUserEmail,
        username: newUsername || undefined,
        password: newUserPassword,
        role: newUserRole,
        team_id: newUserTeam,
        tenant_id: isPlatformAdmin ? (newUserTenant || undefined) : undefined,
      });

      setSuccessMsg(`User '${newUserEmail}' provisioned successfully.`);
      setShowCreateUserModal(false);
      setNewUserEmail('');
      setNewUsername('');
      setNewUserPassword('');
      await fetchDirectoryData();
    } catch (err: any) {
      setErrorMsg(err.response?.data?.detail || 'Failed to provision user.');
    } finally {
      setIsCreatingUser(false);
    }
  };

  const handleUpdateStatus = async (
    targetUser: User,
    updates: { approval_status?: string; is_active?: boolean; role?: string }
  ) => {
    try {
      await authApi.updateUserStatus(targetUser.id, updates);
      setSuccessMsg(`User status updated for ${targetUser.username}.`);
      await fetchDirectoryData();
    } catch (err: any) {
      setErrorMsg(err.response?.data?.detail || 'Failed to update user status.');
    }
  };

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyLabel.trim()) return;
    setIsCreatingKey(true);
    setErrorMsg(null);

    try {
      const res = await authApi.createApiKey({
        label: newKeyLabel,
        role: newKeyRole,
        tenant_id: isPlatformAdmin ? (newKeyTenant || undefined) : undefined,
      });
      setRawGeneratedKey(res.api_key);
      setNewKeyLabel('');
      await fetchDirectoryData();
    } catch (err: any) {
      setErrorMsg(err.response?.data?.detail || 'Failed to generate API key.');
    } finally {
      setIsCreatingKey(false);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    if (!window.confirm('Are you sure you want to revoke this API key? This cannot be undone.')) return;
    try {
      await authApi.deleteApiKey(keyId);
      await fetchDirectoryData();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to revoke API key.');
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(text);
    setTimeout(() => setCopiedKey(null), 2500);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <PageHeader
        title="Identity, RBAC & API Keys"
        subtitle="Authoritative user management, pending registration approvals, and machine-to-machine service tokens"
        actions={
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {isAdmin && (
              <button className="btn btn-primary" onClick={() => setShowCreateUserModal(true)}>
                <UserPlus size={14} />
                <span>Provision User</span>
              </button>
            )}
            <button className="btn btn-secondary" onClick={fetchDirectoryData} disabled={isLoading}>
              <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
              <span>Sync Directory</span>
            </button>
          </div>
        }
      />

      {errorMsg && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            color: '#ef4444',
            padding: '0.85rem 1rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <AlertTriangle size={18} />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.15)',
            border: '1px solid #10b981',
            color: '#10b981',
            padding: '0.85rem 1rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <CheckCircle2 size={18} />
          <span>{successMsg}</span>
        </div>
      )}

      {rawGeneratedKey && (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.12)',
            border: '1px solid #10b981',
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#10b981', fontWeight: 700, fontSize: '0.9rem' }}>
            <CheckCircle2 size={18} />
            <span>API Key Generated Successfully — Store It Securely</span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            This raw key is displayed <strong>ONLY ONCE</strong> and is never stored in plaintext on the server.
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <input
              type="text"
              readOnly
              className="input"
              value={rawGeneratedKey}
              style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: '#34d399' }}
            />
            <button className="btn btn-primary btn-sm" onClick={() => handleCopy(rawGeneratedKey)}>
              <Copy size={14} />
              <span>{copiedKey === rawGeneratedKey ? 'Copied!' : 'Copy Key'}</span>
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setRawGeneratedKey(null)}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Scope banner */}
      {isPlatformAdmin ? (
        <div
          style={{
            background: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            color: '#10b981',
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.82rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.5rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Shield size={16} />
            <span>Platform Admin Global Scope: Managing users, companies, and API keys across all tenants.</span>
          </div>
          {companies.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Building2 size={14} />
              <select
                className="select"
                style={{ padding: '0.2rem 0.6rem', fontSize: '0.78rem' }}
                value={selectedTenantFilter}
                onChange={(e) => setSelectedTenantFilter(e.target.value)}
              >
                <option value="">All Companies / Tenants</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.id})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      ) : isCompanyAdmin ? (
        <div
          style={{
            background: 'rgba(56, 189, 248, 0.08)',
            border: '1px solid rgba(56, 189, 248, 0.25)',
            color: '#38bdf8',
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.82rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <Building2 size={16} />
          <span>Company Admin Scope: Managing users, pending approvals, and service keys within <strong>{user?.tenant_id}</strong>.</span>
        </div>
      ) : null}

      {/* Users Table */}
      <GlassCard title={`Directory Users (${users.length})`}>
        {isLoading ? (
          <LoadingSkeleton rows={4} height={40} />
        ) : users.length === 0 ? (
          <EmptyState
            title="No Users Found"
            description="Directory is empty or no users match the current scope."
            icon={Users}
          />
        ) : (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Identity</th>
                  <th>Role (RBAC)</th>
                  <th>Company / Tenant</th>
                  <th>Team</th>
                  <th>Approval</th>
                  <th>Status</th>
                  {isAdmin && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const apprStatus = u.approval_status || 'APPROVED';
                  return (
                    <tr key={u.id || u.user_id || u.username}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                          <div
                            style={{
                              width: '26px',
                              height: '26px',
                              borderRadius: 'var(--radius-full)',
                              background: 'linear-gradient(135deg, #10b981, #06b6d4)',
                              color: '#090d16',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontWeight: 800,
                              fontSize: '0.72rem',
                            }}
                          >
                            {u.username.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div style={{ fontWeight: 600 }}>{u.username}</div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{u.email}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="badge badge-neutral">{u.role}</span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: '#38bdf8' }}>
                          {u.company_name || u.tenant_id || 'Platform / Global'}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                          {u.team_id || 'N/A'}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            apprStatus === 'APPROVED'
                              ? 'badge-success'
                              : apprStatus === 'PENDING'
                              ? 'badge-warning'
                              : 'badge-danger'
                          }`}
                        >
                          {apprStatus}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontSize: '0.75rem', color: u.is_active ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                          {u.is_active ? '● Active' : '○ Deactivated'}
                        </span>
                      </td>
                      {isAdmin && (
                        <td>
                          <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
                            {apprStatus === 'PENDING' && (
                              <>
                                <button
                                  className="btn btn-secondary btn-sm"
                                  style={{ color: '#10b981', padding: '0.2rem 0.45rem' }}
                                  title="Approve User"
                                  onClick={() => handleUpdateStatus(u, { approval_status: 'APPROVED', is_active: true })}
                                >
                                  <Check size={13} />
                                </button>
                                <button
                                  className="btn btn-secondary btn-sm"
                                  style={{ color: '#ef4444', padding: '0.2rem 0.45rem' }}
                                  title="Reject User"
                                  onClick={() => handleUpdateStatus(u, { approval_status: 'REJECTED', is_active: false })}
                                >
                                  <X size={13} />
                                </button>
                              </>
                            )}
                            {u.is_active ? (
                              <button
                                className="btn btn-secondary btn-sm"
                                style={{ color: '#ef4444', padding: '0.2rem 0.45rem', fontSize: '0.72rem' }}
                                onClick={() => handleUpdateStatus(u, { is_active: false })}
                              >
                                Deactivate
                              </button>
                            ) : (
                              <button
                                className="btn btn-secondary btn-sm"
                                style={{ color: '#10b981', padding: '0.2rem 0.45rem', fontSize: '0.72rem' }}
                                onClick={() => handleUpdateStatus(u, { is_active: true, approval_status: 'APPROVED' })}
                              >
                                Activate
                              </button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* API Key Management */}
      {isAdmin && (
        <GlassCard title="Service Account API Keys (M2M Automation)">
          <form onSubmit={handleCreateKey} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <div className="form-group" style={{ marginBottom: 0, flex: 1, minWidth: '220px' }}>
              <label className="form-label">Service Key Description / Label</label>
              <input
                type="text"
                placeholder="E.g. GitHub Actions Ingest Pipeline"
                className="input"
                value={newKeyLabel}
                onChange={(e) => setNewKeyLabel(e.target.value)}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 0, width: '150px' }}>
              <label className="form-label">Key Role</label>
              <select className="select" value={newKeyRole} onChange={(e) => setNewKeyRole(e.target.value)}>
                <option value="OPERATOR">OPERATOR</option>
                <option value="USER">USER</option>
                <option value="COMPANY_USER">COMPANY_USER</option>
                <option value="VIEWER">VIEWER</option>
              </select>
            </div>

            {isPlatformAdmin && companies.length > 0 && (
              <div className="form-group" style={{ marginBottom: 0, width: '170px' }}>
                <label className="form-label">Target Tenant</label>
                <select className="select" value={newKeyTenant} onChange={(e) => setNewKeyTenant(e.target.value)}>
                  <option value="">Default Tenant</option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            )}

            <button type="submit" className="btn btn-primary" disabled={isCreatingKey || !newKeyLabel.trim()}>
              <Plus size={15} />
              <span>{isCreatingKey ? 'Creating...' : 'Generate Key'}</span>
            </button>
          </form>

          {apiKeys.length === 0 ? (
            <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No API keys generated yet. Service accounts use API keys for automated job ingestion and dispatch.
            </div>
          ) : (
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Label</th>
                    <th>Key Identifier</th>
                    <th>Tenant</th>
                    <th>Role</th>
                    <th>Created At</th>
                    <th>Last Used</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map((k) => (
                    <tr key={k.id}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <Key size={14} style={{ color: '#38bdf8' }} />
                          <span style={{ fontWeight: 600 }}>{k.label || 'Unnamed Key'}</span>
                        </div>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                          {k.id}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: '#38bdf8' }}>
                          {k.tenant_id}
                        </span>
                      </td>
                      <td>
                        <span className="badge badge-neutral">{k.role}</span>
                      </td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {k.created_at ? new Date(k.created_at).toLocaleDateString() : 'N/A'}
                      </td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {k.last_used ? new Date(k.last_used).toLocaleString() : 'Never'}
                      </td>
                      <td>
                        <button
                          className="btn btn-secondary btn-sm"
                          style={{ color: '#ef4444', padding: '0.25rem 0.5rem' }}
                          onClick={() => handleDeleteKey(k.id)}
                          title="Revoke Key"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      )}

      {/* Provision User Modal */}
      {showCreateUserModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.7)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-lg)',
              width: '100%',
              maxWidth: '480px',
              padding: '1.75rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
              boxShadow: 'var(--shadow-xl)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <UserPlus size={18} color="#10b981" />
                <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Provision Platform User</h3>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setShowCreateUserModal(false)}
                style={{ padding: '0.25rem 0.5rem' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateUser} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Email Address *</label>
                <input
                  type="email"
                  required
                  className="input"
                  placeholder="engineer@company.com"
                  value={newUserEmail}
                  onChange={(e) => setNewUserEmail(e.target.value)}
                />
              </div>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Username (optional)</label>
                <input
                  type="text"
                  className="input"
                  placeholder="Defaults to email prefix"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                />
              </div>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Initial Password *</label>
                <input
                  type="password"
                  required
                  className="input"
                  value={newUserPassword}
                  onChange={(e) => setNewUserPassword(e.target.value)}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">Role</label>
                  <select
                    className="select"
                    value={newUserRole}
                    onChange={(e) => setNewUserRole(e.target.value as UserRole)}
                  >
                    <option value="COMPANY_USER">COMPANY_USER</option>
                    <option value="OPERATOR">OPERATOR</option>
                    <option value="VIEWER">VIEWER</option>
                    <option value="COMPANY_ADMIN">COMPANY_ADMIN</option>
                    {isPlatformAdmin && <option value="PLATFORM_ADMIN">PLATFORM_ADMIN</option>}
                  </select>
                </div>

                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">Team ID</label>
                  <input
                    type="text"
                    className="input"
                    value={newUserTeam}
                    onChange={(e) => setNewUserTeam(e.target.value)}
                  />
                </div>
              </div>

              {isPlatformAdmin && companies.length > 0 && (
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label">Company / Tenant</label>
                  <select
                    className="select"
                    value={newUserTenant}
                    onChange={(e) => setNewUserTenant(e.target.value)}
                  >
                    <option value="">Auto / Default</option>
                    {companies.map((c) => (
                      <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
                    ))}
                  </select>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowCreateUserModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isCreatingUser || !newUserEmail.trim() || !newUserPassword}
                >
                  <span>{isCreatingUser ? 'Provisioning...' : 'Confirm Provisioning'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
