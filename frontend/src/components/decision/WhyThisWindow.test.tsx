import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WhyThisWindow } from './WhyThisWindow';
import { fullDecisionWithBaseline, decisionWithRejections } from '../../test/fixtures/scheduleDecision';

describe('WhyThisWindow', () => {
  it('renders nothing when no decision is provided', () => {
    const { container } = render(<WhyThisWindow decision={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the backend's reason verbatim", () => {
    render(<WhyThisWindow decision={fullDecisionWithBaseline} />);
    expect(screen.getByText(fullDecisionWithBaseline.reason)).toBeInTheDocument();
  });

  it('never fabricates an explanation when reason is absent', () => {
    const noReason = { ...fullDecisionWithBaseline, reason: undefined };
    render(<WhyThisWindow decision={noReason} />);
    expect(
      screen.getByText('No explanation was returned by the scheduler for this decision.')
    ).toBeInTheDocument();
    // Must not contain the real reason text from a different fixture, proving nothing
    // was invented to fill the gap.
    expect(screen.queryByText(fullDecisionWithBaseline.reason)).not.toBeInTheDocument();
  });

  it('renders the deterministic rank', () => {
    render(<WhyThisWindow decision={fullDecisionWithBaseline} />);
    expect(screen.getByText('Deterministic Rank #1')).toBeInTheDocument();
  });

  it('renders candidates evaluated and feasible count when returned', () => {
    render(<WhyThisWindow decision={fullDecisionWithBaseline} />);
    expect(screen.getByText('6 candidates evaluated')).toBeInTheDocument();
    expect(screen.getByText('6 feasible')).toBeInTheDocument();
  });

  it('does not render candidate-count chips when the backend omitted them', () => {
    const noCounts = { ...fullDecisionWithBaseline, candidates_evaluated: undefined, feasible_candidates_count: undefined };
    render(<WhyThisWindow decision={noCounts} />);
    expect(screen.queryByText(/candidates evaluated/)).not.toBeInTheDocument();
    // Note: "feasible" also appears inside the unrelated `reason` prose text in this
    // fixture, so match only the dedicated stat chip's exact text ("N feasible").
    expect(screen.queryByText(/^\d+ feasible$/)).not.toBeInTheDocument();
  });

  it('renders the rejection breakdown when returned', () => {
    render(<WhyThisWindow decision={decisionWithRejections} />);
    expect(screen.getByText('deadline exceeded')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('resource conflict')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('shows a neutral message (not fabricated rejections) when nothing was rejected', () => {
    // fullDecisionWithBaseline has an empty rejection_summary and empty rejection_reasons.
    render(<WhyThisWindow decision={fullDecisionWithBaseline} />);
    expect(
      screen.getByText('All evaluated windows met feasibility constraints — none were rejected.')
    ).toBeInTheDocument();
  });

  it('falls back to rejection_reasons list when rejection_summary is absent', () => {
    const withReasonsList = {
      ...fullDecisionWithBaseline,
      rejection_summary: undefined,
      rejection_reasons: ['Deadline conflict on 3 candidates', 'Resource contention on 1 candidate'],
    };
    render(<WhyThisWindow decision={withReasonsList} />);
    expect(screen.getByText('Deadline conflict on 3 candidates')).toBeInTheDocument();
    expect(screen.getByText('Resource contention on 1 candidate')).toBeInTheDocument();
  });

  it('handles an incomplete backend response safely without throwing', () => {
    expect(() => render(<WhyThisWindow decision={{}} />)).not.toThrow();
  });
});
