import React from 'react';
import { CheckCircle2, Cpu, ArrowRight, Eye } from 'lucide-react';
import { JobSubmitResult } from '../../types/api';

interface SubmissionSuccessProps {
  result: JobSubmitResult;
  onViewScheduling: () => void;
  onViewWorkload: () => void;
}

export const SubmissionSuccess: React.FC<SubmissionSuccessProps> = ({ result, onViewScheduling, onViewWorkload }) => (
  <div
    style={{
      background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(6, 182, 212, 0.1))',
      border: '1px solid #10b981',
      borderRadius: 'var(--radius-md)',
      padding: '1.5rem',
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
      <CheckCircle2 size={24} color="#10b981" />
      <div>
        <h3 style={{ color: '#ffffff' }}>Workload submitted successfully</h3>
        {result.name && <p style={{ fontSize: '0.95rem', fontWeight: 600, color: '#ffffff', marginTop: '0.2rem' }}>{result.name}</p>}
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
          Job ID <strong style={{ fontFamily: 'var(--font-mono)', color: '#38bdf8' }}>{result.job_id}</strong>
        </p>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
          Your workload has been registered and is ready for scheduling.
        </p>
      </div>
    </div>

    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
      <button className="btn btn-primary" onClick={onViewScheduling}>
        <Cpu size={15} />
        <span>View Scheduling Recommendation</span>
        <ArrowRight size={14} />
      </button>
      <button className="btn btn-secondary" onClick={onViewWorkload}>
        <Eye size={14} />
        <span>View Workload</span>
      </button>
    </div>
  </div>
);
