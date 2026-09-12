import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SchedulingSummary } from './SchedulingSummary';
import { WorkloadDetail } from '../../types/api';

const baseJob: WorkloadDetail = {
  job_id: 'JOB-TIME-001',
  team_id: 'team-a',
  status: 'SCHEDULED' as any,
  submitted_at: '2026-09-10T00:00:00Z',
  deadline: '2026-09-10T18:00:00Z',
  runtime_minutes: 120,
  power_kw: 3.0,
  region: 'IN-TG',
  container_image: 'python:3.10-slim',
  schedule_decision: {
    job_id: 'JOB-TIME-001',
    selected_start: '2026-09-10T14:00:00Z',
    selected_end: '2026-09-10T16:00:00Z',
    carbon_intensity: 400,
    electricity_cost: 0.5,
    carbon_emission: 0.4,
    region_id: 'IN-TG',
    currency: 'USD',
    candidates_evaluated: 4,
    feasible_candidates_count: 4,
  } as any,
};

describe('SchedulingSummary — requested window (Time Consistency Hardening)', () => {
  it('shows the requested earliest start when the job has one', () => {
    const job = { ...baseJob, earliest_start_time: '2026-09-10T10:00:00Z' };
    render(
      <SchedulingSummary job={job} onFindSchedule={vi.fn()} isScheduling={false} onViewFullAnalysis={vi.fn()} timezoneName="Asia/Kolkata" />
    );
    expect(screen.getByText('Requested Earliest Start')).toBeInTheDocument();
  });

  it('omits the earliest-start row when the job has none (never fabricates one)', () => {
    const job = { ...baseJob, earliest_start_time: null };
    render(
      <SchedulingSummary job={job} onFindSchedule={vi.fn()} isScheduling={false} onViewFullAnalysis={vi.fn()} timezoneName="Asia/Kolkata" />
    );
    expect(screen.queryByText('Requested Earliest Start')).not.toBeInTheDocument();
  });

  it('always shows the requested deadline', () => {
    render(
      <SchedulingSummary job={baseJob} onFindSchedule={vi.fn()} isScheduling={false} onViewFullAnalysis={vi.fn()} timezoneName="Asia/Kolkata" />
    );
    expect(screen.getByText('Requested Deadline')).toBeInTheDocument();
  });
});
