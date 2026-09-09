import React from 'react';

interface LoadingSkeletonProps {
  rows?: number;
  height?: number;
  className?: string;
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({
  rows = 4,
  height = 36,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', width: '100%' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: `${height}px`,
            borderRadius: 'var(--radius-sm)',
            background: 'linear-gradient(90deg, var(--bg-surface-elevated) 25%, var(--bg-surface-hover) 50%, var(--bg-surface-elevated) 75%)',
            backgroundSize: '200% 100%',
            animation: 'skeletonShimmer 1.5s infinite linear',
          }}
        />
      ))}
      <style>{`
        @keyframes skeletonShimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
};
