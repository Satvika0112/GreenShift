import { PendingApprovalItem } from '../types/api';
import { formatCarbonKg, formatCost, formatDateTime } from './workloadDisplay';

export function estimatedCarbonDisplay(item: Pick<PendingApprovalItem, 'carbon_emission_kg'>): string {
  return formatCarbonKg(item.carbon_emission_kg, { estimated: true });
}

export function estimatedCostDisplay(item: Pick<PendingApprovalItem, 'native_cost' | 'currency' | 'electricity_cost_usd'>): string {
  return formatCost({ native_cost: item.native_cost, currency: item.currency, electricity_cost: item.electricity_cost_usd });
}

export function baselineCarbonDisplay(item: Pick<PendingApprovalItem, 'baseline_carbon_emission_kg'>): string {
  return formatCarbonKg(item.baseline_carbon_emission_kg, { estimated: true });
}

export function baselineCostDisplay(item: Pick<PendingApprovalItem, 'baseline_native_cost' | 'currency' | 'baseline_cost_usd'>): string {
  return formatCost({ native_cost: item.baseline_native_cost, currency: item.currency, electricity_cost: item.baseline_cost_usd });
}

// Converts from the UTC value + the item's own IANA timezone (rather than
// trusting the precomputed `_local` field's embedded numeric offset) so this
// goes through the one shared formatter like every other page.
export function baselineStartDisplay(item: Pick<PendingApprovalItem, 'baseline_start_utc' | 'timezone'>): string {
  return item.baseline_start_utc ? formatDateTime(item.baseline_start_utc, item.timezone) : '—';
}

// The backend already computes carbon_reduction_pct on the schedule
// decision — this only relays that real, stored value. It is never
// recomputed or estimated client-side, and is omitted entirely (not
// zero-filled) when the backend hasn't provided it.
export function carbonReductionDisplay(item: Pick<PendingApprovalItem, 'carbon_reduction_pct'>): string | null {
  const pct = item.carbon_reduction_pct;
  if (pct === undefined || pct === null || Number.isNaN(pct)) return null;
  const rounded = Math.round(pct);
  return `${rounded >= 0 ? '↓' : '↑'} ${Math.abs(rounded)}% carbon`;
}

export interface CarbonBudgetStatus {
  text: string;
  withinBudget: boolean | null;
}

// A budget-vs-estimate comparison is a plain numeric comparison of two real
// backend values — not a fabrication. Compliance is only claimed when both
// numbers are actually present.
export function carbonBudgetStatus(item: Pick<PendingApprovalItem, 'carbon_budget_kg' | 'carbon_emission_kg'>): CarbonBudgetStatus {
  if (item.carbon_budget_kg === undefined || item.carbon_budget_kg === null) {
    return { text: 'No carbon budget', withinBudget: null };
  }
  const budgetText = `${item.carbon_budget_kg} kg CO₂`;
  if (item.carbon_emission_kg === undefined || item.carbon_emission_kg === null) {
    return { text: budgetText, withinBudget: null };
  }
  const withinBudget = item.carbon_emission_kg <= item.carbon_budget_kg;
  return { text: `${budgetText} ${withinBudget ? '✓' : '✗'}`, withinBudget };
}

export type SlaStatus = 'WITHIN_DEADLINE' | 'DEADLINE_CONFLICT' | 'UNAVAILABLE';

// sla_met is a real boolean the backend already computes
// (completion <= deadline). No independent frontend SLA algorithm — when
// the backend hasn't provided it, this reports unavailable rather than
// inventing an "at risk" tier the backend has no signal for.
export function slaStatus(item: Pick<PendingApprovalItem, 'sla_met'>): { status: SlaStatus; label: string } {
  if (item.sla_met === undefined || item.sla_met === null) {
    return { status: 'UNAVAILABLE', label: 'Unavailable' };
  }
  return item.sla_met
    ? { status: 'WITHIN_DEADLINE', label: 'Within deadline' }
    : { status: 'DEADLINE_CONFLICT', label: 'Deadline conflict' };
}

export function approvalContextText(reason?: string | null): string {
  return reason && reason.trim() ? reason : 'Schedule requires human authorization before execution.';
}

// Only backend-confirmed scheduling semantics — never a fleet-level or
// speculative claim.
export function whyThisScheduleText(): string {
  return "Lowest-carbon feasible window that satisfies the workload's deadline, resource requirements, region constraints, and carbon budget.";
}
