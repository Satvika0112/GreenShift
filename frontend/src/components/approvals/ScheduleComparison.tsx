import React from 'react';
import { PendingApprovalItem } from '../../types/api';
import {
  estimatedCarbonDisplay,
  estimatedCostDisplay,
  baselineCarbonDisplay,
  baselineCostDisplay,
  baselineStartDisplay,
} from '../../utils/approvalDisplay';
import { formatDateTime } from '../../utils/workloadDisplay';

interface ScheduleComparisonProps {
  item: PendingApprovalItem;
}

// Every cell here is either a real backend baseline/recommended value or an
// honest "—" — never a computed or invented figure.
export const ScheduleComparison: React.FC<ScheduleComparisonProps> = ({ item }) => {
  const hasBaseline = item.baseline_carbon_emission_kg !== undefined && item.baseline_carbon_emission_kg !== null;

  return (
    <div>
      <h4 style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
        Comparison
      </h4>
      <div className="data-table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th></th>
              <th>Immediate Execution</th>
              <th>GreenShift</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Carbon</td>
              <td>{hasBaseline ? baselineCarbonDisplay(item) : '—'}</td>
              <td style={{ color: '#10b981', fontWeight: 600 }}>{estimatedCarbonDisplay(item)}</td>
            </tr>
            <tr>
              <td>Cost</td>
              <td>{item.baseline_cost_usd !== undefined && item.baseline_cost_usd !== null ? baselineCostDisplay(item) : '—'}</td>
              <td style={{ color: '#38bdf8', fontWeight: 600 }}>{estimatedCostDisplay(item)}</td>
            </tr>
            <tr>
              <td>Start</td>
              <td>{baselineStartDisplay(item)}</td>
              <td>{formatDateTime(item.selected_start_utc, item.timezone)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};
