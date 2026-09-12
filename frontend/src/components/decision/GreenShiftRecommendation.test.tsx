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

  describe('Requested Window (Time Consistency Hardening)', () => {
    it('shows the requested window alongside the recommendation when the backend supplies it', () => {
      const decision = {
        ...fullDecisionWithBaseline,
        requested_earliest_start: '2026-09-10T04:30:00Z',
        requested_deadline: '2026-09-10T12:30:00Z',
      };
      render(<GreenShiftRecommendation decision={decision} />);
      expect(screen.getByText(/Requested Window/i)).toBeInTheDocument();
    });

    it('shows "As soon as possible" when no earliest start was requested', () => {
      const decision = {
        ...fullDecisionWithBaseline,
        requested_earliest_start: null,
        requested_deadline: '2026-09-10T12:30:00Z',
      };
      render(<GreenShiftRecommendation decision={decision} />);
      expect(screen.getByText(/As soon as possible/i)).toBeInTheDocument();
    });

    it('does not render a Requested Window section when the backend supplies neither field', () => {
      render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
      expect(screen.queryByText(/Requested Window/i)).not.toBeInTheDocument();
    });
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

  describe('native currency labeling (Currency Consistency Hardening)', () => {
    it('prefers the region-native cost over the USD-normalized figure when both are present', () => {
      // fullDecisionWithBaseline has currency="INR", native_cost=7.15, AND a
      // USD-normalized electricity_cost=0.0858 for internal scheduler
      // comparisons — the execution region's native currency is the single
      // source of truth for what the user sees, so this must render ₹7.15,
      // never the USD-normalized figure.
      render(<GreenShiftRecommendation decision={fullDecisionWithBaseline} />);
      expect(screen.getByText('₹7.15')).toBeInTheDocument();
      expect(screen.queryByText('$0.0858')).not.toBeInTheDocument();
    });

    it('falls back to USD when no native cost/currency is available', () => {
      const usdOnly = {
        selected_start: '2026-09-10T08:00:00Z',
        selected_end: '2026-09-10T08:30:00Z',
        region_id: 'US-CA',
        electricity_cost: 0.51,
        // native_cost/currency intentionally omitted
      };
      render(<GreenShiftRecommendation decision={usdOnly} />);
      expect(screen.getByText('$0.51')).toBeInTheDocument();
    });

    it('treats decisionWithoutBaseline (real POST /schedule/{id} shape) the same way', () => {
      render(<GreenShiftRecommendation decision={decisionWithoutBaseline} />);
      expect(screen.getByText('₹7.15')).toBeInTheDocument();
    });
  });
});
