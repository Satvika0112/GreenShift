import { User } from '../../types/api';

// Matches GET /api/v1/admin/users item shape.
export const approvedAdminUser: User = {
  id: 1,
  username: 'company_admin',
  email: 'admin@acme.example',
  role: 'COMPANY_ADMIN' as any,
  team_id: 'team-acme',
  tenant_id: 'acme',
  company_name: 'Acme Corp',
  approval_status: 'APPROVED',
  is_active: true,
};

export const pendingUser: User = {
  id: 2,
  username: 'new_hire',
  email: 'new_hire@acme.example',
  role: 'COMPANY_USER' as any,
  team_id: 'team-acme',
  tenant_id: 'acme',
  company_name: 'Acme Corp',
  approval_status: 'PENDING',
  is_active: false,
};

export const apiKeyFixture = {
  id: 'key-abc123',
  label: 'CI Ingest Pipeline',
  tenant_id: 'acme',
  role: 'COMPANY_USER',
  created_at: '2026-08-01T00:00:00Z',
  last_used: null,
};

export const companyFixture = { id: 'acme', name: 'Acme Corp' };
