import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GreenShiftRecommendation } from './GreenShiftRecommendation';
import { fullDecisionWithBaseline, decisionWithoutBaseline } from '../../test/fixtures/scheduleDecision';

describe('GreenShiftRecommendation', () => {
  it('renders nothing when no decision is provided', () => {
    const { container } = render(<GreenShiftRecommendation decision={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('displays the selected window', () => {
    render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
    // formatWindow renders month/day/hour/minute — assert the date portion is present
    // via a loose text match rather than pinning an exact locale string.
    expect(screen.getByText(/Recommended Window/i)).toBeInTheDocument();
  });

  it('displays the selected region', () => {
    render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
    expect(screen.getByText('IN-TG')).toBeInTheDocument();
  });

  it('falls back to the job region when the decision has none', () => {
    const decisionNoRegion = { ...fullDecisionWithBaseline, region_id: undefined };
    render(<GreenShiftRecommendation decision={decisionNoRegion} fallbackRegion="IN-GJ" />);
    expect(screen.getByText('IN-GJ')).toBeInTheDocument();
  });

  it('displays carbon intensity and emissions when provided', () => {
    render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
    expect(screen.getByText('406.0 gCO₂/kWh')).toBeInTheDocument();
    expect(screen.getByText('0.406 kg')).toBeInTheDocument();
    // carbon_reduction_pct=0.73 is rendered rounded to 1 decimal place (toFixed(1)).
    expect(screen.getByText(/0\.7% vs baseline/)).toBeInTheDocument();
  });

  it('displays the deterministic rank', () => {
    render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
    expect(screen.getByText(/Rank #1/)).toBeInTheDocument();
  });

  it('displays scheduling delay and SLA outcome when provided', () => {
    render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
    expect(screen.getByText('1.7h')).toBeInTheDocument();
    expect(screen.getByText('SLA MET')).toBeInTheDocument();
  });

  it('shows an "at risk" SLA badge when sla_met is false', () => {
    const decision = { ...fullDecisionWithBaseline, sla_met: false };
    render(<GreenShiftRecommendation decision={decision} />);
    expect(screen.getByText('SLA AT RISK')).toBeInTheDocument();
  });

  it('handles missing optional fields safely (delay/SLA absent)', () => {
    const minimal = {
      selected_start: '2026-09-10T08:00:00Z',
      selected_end: '2026-09-10T08:30:00Z',
      region_id: 'IN-TG',
    };
    expect(() => render(<GreenShiftRecommendation decision={minimal} />)).not.toThrow();
    // Delay/SLA rows must not render fabricated values when absent.
    expect(screen.queryByText(/Scheduling Delay/)).not.toBeInTheDocument();
    expect(screen.queryByText(/SLA Outcome/)).not.toBeInTheDocument();
  });

  describe('USD vs native currency labeling (regression)', () => {
    it('does NOT label the USD-normalized electricity_cost with the native currency', () => {
      // fullDecisionWithBaseline has currency="INR" but electricity_cost is USD-normalized.
      render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
      // The real value is 0.0858 USD -> "$0.0858". It must never render as "0.0858 INR".
      expect(screen.getByText('$0.0858')).toBeInTheDocument();
      expect(screen.queryByText(/0\.0858\s*INR/)).not.toBeInTheDocument();
    });

    it('DOES label native_cost with the native currency when electricity_cost is absent', () => {
      const nativeOnly = {
        selected_start: '2026-09-10T08:00:00Z',
        selected_end: '2026-09-10T08:30:00Z',
        region_id: 'IN-TG',
        currency: 'INR',
        native_cost: 7.15,
        // electricity_cost intentionally omitted
      };
      render(<GreenShiftRecommendation decision={nativeOnly} />);
      expect(screen.getByText('₹7.15')).toBeInTheDocument();
    });

    it('treats decisionWithoutBaseline (real POST /schedule/{id} shape) the same way', () => {
      render(<GreenShiftRecommendation decision={decisionWithoutBaseline} />);
      expect(screen.getByText('$0.0858')).toBeInTheDocument();
    });
  });
});
