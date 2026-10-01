'use client';

import { useEffect, useState } from 'react';
import { Check, LoaderCircle, X } from 'lucide-react';
import { ScoreProof } from '@/components/ScoreBreakdown';
import type { Theme, ThemeActivity } from '@/utils/types';

function since(iso?: string | null) {
  if (!iso) return '';
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function describeActivity(item: ThemeActivity) {
  const verb = item.action === 'approved' && item.changed_title ? 'Approved with edits' : item.action.charAt(0).toUpperCase() + item.action.slice(1);
  return `${verb} by ${item.by}${item.at ? `, ${since(item.at)}` : ''}`;
}

type Props = {
  theme: Theme | null;
  canEdit: boolean;
  demoLocked: boolean;
  working: string;
  onClose: () => void;
  onApprove: (theme: Theme, edits?: { title: string; summary: string }) => void;
  onReject: (theme: Theme) => void;
};

export default function EvidencePanel({ theme, canEdit, demoLocked, working, onClose, onApprove, onReject }: Props) {
  const [editTitle, setEditTitle] = useState('');
  const [editSummary, setEditSummary] = useState('');

  // Reset editable fields when theme changes
  useEffect(() => {
    if (theme) {
      setEditTitle(theme.title);
      setEditSummary(theme.summary);
    }
  }, [theme]);

  // Keyboard shortcuts: Escape to close, Cmd+Enter to approve
  useEffect(() => {
    if (!theme) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canEdit && !demoLocked && editTitle.trim()) {
        e.preventDefault();
        onApprove(theme, { title: editTitle, summary: editSummary });
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Backspace' && canEdit && !demoLocked) {
        e.preventDefault();
        onReject(theme);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [theme, canEdit, demoLocked, editTitle, editSummary, onClose, onApprove, onReject]);

  if (!theme) return null;

  const edited = editTitle.trim() !== theme.title || editSummary.trim() !== theme.summary;

  return (
    <>
      <div className="slide-over-backdrop" onClick={onClose} />
      <aside className="slide-over" role="dialog" aria-modal="true" aria-label="Theme evidence">
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {/* Header */}
          <div className="flex items-start justify-between gap-3">
            <p className="text-[13px] text-muted">{theme.score_breakdown ? `Ranked ${theme.score_breakdown.rank} of ${theme.score_breakdown.of}` : 'Theme'}</p>
            <button onClick={onClose} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>
          </div>

          {/* Editable title and summary */}
          <label className="mt-1 block text-[13px] font-medium text-muted">Title
            <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} disabled={!canEdit || demoLocked} className="field mt-1 w-full text-[16px] font-semibold"/>
          </label>
          <label className="mt-3 block text-[13px] font-medium text-muted">Problem
            <textarea value={editSummary} onChange={(e) => setEditSummary(e.target.value)} disabled={!canEdit || demoLocked} rows={3} className="field mt-1 w-full resize-y leading-relaxed"/>
          </label>
          {edited && <p className="mt-2 text-[12px] text-caution">Edited. Approving now records it as approved with edits.</p>}
          {!canEdit && <p className="mt-3 text-[13px] text-muted">You have view-only access, so you can read the evidence but not approve or reject.</p>}

          {/* Quotes */}
          <h3 className="mt-6 text-[15px] font-semibold text-ink">What customers said</h3>
          {theme.cited_quotes?.length ? (
            <ul className="mt-2">{theme.cited_quotes.map((quote, i) => (
              <li key={i} className={`py-3 ${i ? 'border-t border-rule' : ''}`}>
                <blockquote className="quote">&ldquo;<span className="marked">{quote.quote_text}</span>&rdquo;</blockquote>
                <p className="mt-1 text-[13px] text-muted">{[quote.customer_id, quote.customer_id && quote.customer_tier && quote.customer_tier !== 'free' ? `${quote.customer_tier} plan` : null, quote.source_name].filter(Boolean).join(', ') || 'From your sources'}</p>
              </li>
            ))}</ul>
          ) : <p className="mt-2 text-muted">No verified quotes for this theme.</p>}

          {/* Score proof */}
          <ScoreProof breakdown={theme.score_breakdown}/>

          {/* Activity history */}
          {theme.activity?.length ? <>
            <h3 className="mt-6 text-[15px] font-semibold text-ink">History</h3>
            <ul className="mt-1 text-[13px] text-muted" aria-label="History">{theme.activity.map((item, i) => <li key={i} className="py-0.5">{describeActivity(item)}</li>)}</ul>
          </> : null}

          {/* Keyboard shortcut hints */}
          <p className="mt-6 text-[11px] text-faint">
            <kbd className="rounded border border-rule bg-paper px-1 py-0.5 font-mono text-[10px]">Esc</kbd> close
            {canEdit && !demoLocked && <>
              {' · '}<kbd className="rounded border border-rule bg-paper px-1 py-0.5 font-mono text-[10px]">⌘↵</kbd> approve
              {' · '}<kbd className="rounded border border-rule bg-paper px-1 py-0.5 font-mono text-[10px]">⌘⌫</kbd> reject
            </>}
          </p>
        </div>

        {/* Sticky action bar */}
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-rule bg-surface px-6 py-4">
          <button onClick={onClose} className="btn-text mr-auto">Close</button>
          {demoLocked ? (
            <button onClick={() => onApprove(theme)} disabled={Boolean(working)} className="btn-primary">
              {working === theme.id && <LoaderCircle size={14} className="animate-spin"/>} Preview PRD
            </button>
          ) : <>
            <button onClick={() => onReject(theme)} disabled={Boolean(working) || !canEdit} className="btn-danger">Reject</button>
            <button onClick={() => onApprove(theme, { title: editTitle, summary: editSummary })} disabled={Boolean(working) || !editTitle.trim() || !canEdit} title="Writes the PRD and opens a GitHub issue" className="btn-primary">
              {working === theme.id ? <LoaderCircle size={14} className="animate-spin"/> : <Check size={14}/>} Approve
            </button>
          </>}
        </div>
      </aside>
    </>
  );
}
