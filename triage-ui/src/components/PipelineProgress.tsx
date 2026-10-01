'use client';

import { Check, LoaderCircle } from 'lucide-react';
import type { PipelineProgress as ProgressType } from '@/utils/api';

const STAGES = [['embedding', 'Reading passages'], ['clustering', 'Finding patterns'], ['labelling', 'Naming themes'], ['saving', 'Saving']] as const;

type Props = {
  progress: ProgressType | null;
  working: string;
};

export default function PipelineProgress({ progress, working }: Props) {
  if (working !== 'pipeline') return null;

  const stageIndex = progress?.stage ? STAGES.findIndex(([key]) => key === progress.stage) : -1;
  const stageFraction = progress && progress.total > 0 ? Math.min(progress.done / progress.total, 1) : 0;
  const percent = progress?.stage ? Math.round(((Math.max(stageIndex, 0) + (progress.stage === 'labelling' ? stageFraction : 0)) / STAGES.length) * 100) : 0;

  // Estimated time remaining during labelling stage
  const eta = progress?.stage === 'labelling' && progress.done > 0 && progress.elapsed_seconds
    ? Math.round((progress.elapsed_seconds / progress.done) * (progress.total - progress.done))
    : null;

  return (
    <div className="panel mb-5 px-4 py-3.5" role="status" aria-live="polite">
      <div className="flex items-center justify-between gap-3 text-[13px]">
        <span className="flex items-center gap-2 font-medium text-ink">
          <LoaderCircle size={14} className="animate-spin text-action"/>
          {progress?.stage ? STAGES[stageIndex]?.[1] ?? 'Processing' : 'Starting the analysis'}
          {progress?.stage === 'labelling' && progress.total > 0 ? ` (${progress.done} of ${progress.total} themes)` : ''}
        </span>
        <span className="tnum flex items-center gap-2 text-muted">
          {eta !== null && <span className="text-faint">~{eta}s remaining</span>}
          {progress?.elapsed_seconds != null ? `${Math.round(progress.elapsed_seconds)}s` : ''}
        </span>
      </div>
      <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-paper">
        <div className="h-full rounded-full bg-action transition-all duration-500" style={{ width: `${Math.max(percent, 4)}%` }}/>
      </div>
      <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
        {STAGES.map(([key, label], index) => (
          <li key={key} className={index < stageIndex ? 'text-action' : index === stageIndex ? 'font-medium text-ink' : ''}>
            {index < stageIndex ? <Check size={12} className="mr-1 inline"/> : null}{label}
          </li>
        ))}
      </ol>
    </div>
  );
}
