import React, { useState, useEffect } from 'react';
import {
  Users,
  Shield,
  Key,
  Plus,
  Trash2,
  Copy,
  CheckCircle2,
  RefreshCw,
  AlertTriangle,
  Lock,
} from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassCard } from '../components/common/GlassCard';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { authApi } from '../api/endpoints';
import { User } from '../types/api';
import { useAuth } from '../context/AuthContext';

export const UsersAccessPage: React.FC = () => {
  const { user, isAdmin } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [newKeyLabel, setNewKeyLabel] = useState('');
  const [newKeyRole, setNewKeyRole] = useState('OPERATOR');
  const [rawGeneratedKey, setRawGeneratedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchUsersAndKeys = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      if (isAdmin) {
        const [usersRes, keysRes] = await Promise.allSettled([
          authApi.getUsers(),
          authApi.listApiKeys(),
        ]);

        if (usersRes.status === 'fulfilled' && Array.isArray(usersRes.value)) {
          setUsers(usersRes.value);
        }
        if (keysRes.status === 'fulfilled' && Array.isArray(keysRes.value)) {
          setApiKeys(keysRes.value);
        }
      } else if (user) {
        setUsers([user]);
      }
    } catch (err: any) {
      setErrorMsg(err.response?.data?.detail || 'Failed to fetch users or API keys from backend.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchUsersAndKeys();
  }, [user]);

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyLabel.trim()) return;
    setIsCreatingKey(true);
    setErrorMsg(null);

    try {
      const res = await authApi.createApiKey({
        label: newKeyLabel,
        role: newKeyRole,
      });
      setRawGeneratedKey(res.api_key);
      setNewKeyLabel('');
      await fetchUsersAndKeys();
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
      await fetchUsersAndKeys();
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
        subtitle="Role-based access control, team boundary isolation, and machine-to-machine authentication tokens"
        actions={
          <button className="btn btn-secondary" onClick={fetchUsersAndKeys} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Sync Directory</span>
          </button>
        }
      />

      {errorMsg && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            color: '#ef4444',
            padding: '1rem',
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

      {!isAdmin && (
        <div
          style={{
            background: 'rgba(56, 189, 248, 0.08)',
            border: '1px solid rgba(56, 189, 248, 0.25)',
            color: '#38bdf8',
            padding: '0.85rem 1rem',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.82rem',
          }}
        >
          ℹ Currently authenticated as <strong>{user?.username}</strong> ({user?.role}). Full multi-tenant user and API key administration is restricted to the <strong>ADMIN</strong> role.
        </div>
      )}

      {/* Users Table */}
      <GlassCard title={`Registered Platform Users (${users.length})`}>
        {isLoading ? (
          <LoadingSkeleton rows={4} height={40} />
        ) : users.length === 0 ? (
          <EmptyState
            title="No Users Found"
            description="Directory is empty or could not be queried."
            icon={Users}
          />
        ) : (
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Role (RBAC)</th>
                  <th>Team Scope</th>
                  <th>Email</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
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
                        <span style={{ fontWeight: 600 }}>{u.username}</span>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          u.role === 'ADMIN'
                            ? 'badge-success'
                            : u.role === 'TEAM_LEAD'
                            ? 'badge-info'
                            : u.role === 'OPERATOR'
                            ? 'badge-warning'
                            : 'badge-neutral'
                        }`}
                      >
                        {u.role}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>
                        {u.team_id || 'Global / N/A'}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{u.email}</span>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.75rem', color: '#10b981', fontWeight: 600 }}>
                        {u.is_active !== false ? '● Active' : '○ Deactivated'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {/* API Key Management (Admin only) */}
      {isAdmin && (
        <GlassCard title="Service Account API Keys (M2M Automation)">
          <form onSubmit={handleCreateKey} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <div className="form-group" style={{ marginBottom: 0, flex: 1, minWidth: '240px' }}>
              <label className="form-label">Service Key Description / Label</label>
              <input
                type="text"
                placeholder="E.g. GitHub Actions CI/CD Ingest Pipeline"
                className="input"
                value={newKeyLabel}
                onChange={(e) => setNewKeyLabel(e.target.value)}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 0, width: '160px' }}>
              <label className="form-label">Key Role</label>
              <select className="select" value={newKeyRole} onChange={(e) => setNewKeyRole(e.target.value)}>
                <option value="OPERATOR">OPERATOR</option>
                <option value="TEAM_LEAD">TEAM_LEAD</option>
                <option value="VIEWER">VIEWER</option>
              </select>
            </div>

            <button type="submit" className="btn btn-primary" disabled={isCreatingKey || !newKeyLabel.trim()}>
              <Plus size={15} />
              <span>{isCreatingKey ? 'Creating...' : 'Generate Key'}</span>
            </button>
          </form>

          {apiKeys.length === 0 ? (
            <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              No API keys generated yet. Machine-to-machine integrations use API keys for automated job ingestion and dispatch.
            </div>
          ) : (
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Label</th>
                    <th>Key Identifier</th>
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
    </div>
  );
};
