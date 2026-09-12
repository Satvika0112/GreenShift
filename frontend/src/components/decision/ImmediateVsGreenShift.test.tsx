import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ImmediateVsGreenShift } from './ImmediateVsGreenShift';
import { fullDecisionWithBaseline, decisionWithoutBaseline } from '../../test/fixtures/scheduleDecision';

describe('ImmediateVsGreenShift', () => {
  it('renders nothing when no decision is provided', () => {
    const { container } = render(<ImmediateVsGreenShift decision={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  describe('CRITICAL: no fabricated baseline', () => {
    it('renders nothing at all when the backend gives no baseline whatsoever', () => {
      const noBaselineAtAll = {
        selected_start: '2026-09-10T08:00:00Z',
        selected_end: '2026-09-10T08:30:00Z',
        region_id: 'IN-TG',
        carbon_emission: 0.406,
        electricity_cost: 0.0858,
        // No baseline_carbon_emission, baseline_cost, or baseline_native_cost at all.
      };
      const { container } = render(<ImmediateVsGreenShift decision={noBaselineAtAll} />);
      expect(container).toBeEmptyDOMElement();
    });

    it('does not copy GreenShift values into the baseline column when baseline is missing', () => {
      const noBaselineAtAll = {
        selected_start: '2026-09-10T08:00:00Z',
        selected_end: '2026-09-10T08:30:00Z',
        carbon_emission: 0.406,
        electricity_cost: 0.0858,
      };
      render(<ImmediateVsGreenShift decision={noBaselineAtAll} />);
      // Nothing rendered at all -- in particular no "IMMEDIATE EXECUTION" section
      // showing the GreenShift-optimized figures relabeled as a baseline.
      expect(screen.queryByText('IMMEDIATE EXECUTION')).not.toBeInTheDocument();
      expect(screen.queryByText('0.406 kg')).not.toBeInTheDocument();
    });

    it('renders the real backend response shape from POST /schedule/{id} that lacks baseline_carbon_emission/baseline_cost (but has baseline_native_cost, so cost still compares)', () => {
      render(<ImmediateVsGreenShift decision={decisionWithoutBaseline} />);
      // Carbon baseline is genuinely absent in this real response shape -> no carbon comparison rendered.
      expect(screen.queryByText('Carbon Emissions')).not.toBeInTheDocument();
      // But baseline_native_cost IS present, so a cost comparison legitimately renders.
      expect(screen.getAllByText('Electricity Cost').length).toBeGreaterThan(0);
    });
  });

  describe('with a real baseline present', () => {
    it('renders the baseline vs GreenShift comparison', () => {
      render(<ImmediateVsGreenShift decision={fullDecisionWithBaseline} />);
      expect(screen.getByText('IMMEDIATE EXECUTION')).toBeInTheDocument();
      expect(screen.getByText('GREENSHIFT')).toBeInTheDocument();
    });

    it('displays the baseline carbon emissions and the GreenShift carbon emissions', () => {
      render(<ImmediateVsGreenShift decision={fullDecisionWithBaseline} />);
      expect(screen.getByText('0.409 kg')).toBeInTheDocument(); // baseline_carbon_emission
      expect(screen.getByText('0.406 kg')).toBeInTheDocument(); // carbon_emission
    });

    it('prefers the region-native cost over the USD-normalized figure for both columns', () => {
      // fullDecisionWithBaseline: currency="INR", native_cost=baseline_native_cost=7.15 —
      // the execution region's native currency is the single source of truth,
      // so both columns must show ₹7.15, never the USD-normalized 0.0858 figure.
      render(<ImmediateVsGreenShift decision={fullDecisionWithBaseline} />);
      const nativeValues = screen.getAllByText('₹7.15');
      expect(nativeValues.length).toBe(2); // one for baseline, one for GreenShift
      expect(screen.queryByText('$0.0858')).not.toBeInTheDocument();
    });

    it('labels native-currency-only costs correctly when USD fields are absent', () => {
      const nativeOnlyBoth = {
        selected_start: '2026-09-10T08:00:00Z',
        selected_end: '2026-09-10T08:30:00Z',
        currency: 'INR',
        native_cost: 7.15,
        baseline_native_cost: 8.0,
        // electricity_cost / baseline_cost intentionally absent
      };
      render(<ImmediateVsGreenShift decision={nativeOnlyBoth} />);
      expect(screen.getByText('₹8.00')).toBeInTheDocument();
      expect(screen.getByText('₹7.15')).toBeInTheDocument();
    });

    it('displays scheduling delay and SLA when provided', () => {
      render(<ImmediateVsGreenShift decision={fullDecisionWithBaseline} />);
      expect(screen.getByText(/1\.7h/)).toBeInTheDocument();
      expect(screen.getByText('MET')).toBeInTheDocument();
    });
  });
});
