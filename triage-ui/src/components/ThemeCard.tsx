'use client';

import { Check, LoaderCircle } from 'lucide-react';
import { ScoreStrip } from '@/components/ScoreBreakdown';
import type { Theme, ThemeActivity } from '@/utils/types';

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;

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

function whoSaid(quote: NonNullable<Theme['cited_quotes']>[number]) {
  return [quote.customer_id, quote.source_name].filter(Boolean).join(', ') || 'From your sources';
}

function riskBorder(revenue: number): string {
  if (revenue >= 100_000) return 'border-l-[3px] border-l-danger';
  if (revenue >= 10_000) return 'border-l-[3px] border-l-caution';
  if (revenue > 0) return 'border-l-[3px] border-l-action';
  return '';
}

type Props = {
  theme: Theme;
  index: number;
  working: string;
  canEdit: boolean;
  demoLocked: boolean;
  onApprove: (theme: Theme) => void;
  onReject: (theme: Theme) => void;
  onOpenEvidence: (theme: Theme) => void;
};

export default function ThemeCard({ theme, index, working, canEdit, demoLocked, onApprove, onReject, onOpenEvidence }: Props) {
  const rank = theme.score_breakdown?.rank ?? index + 1;
  const quote = theme.cited_quotes?.[0];
  const moreQuotes = (theme.cited_quotes?.length || 0) - 1;
  const last = theme.activity?.[0];
  const breakdown = theme.score_breakdown;
  const verdict = breakdown?.verdict;

  return (
    <li
      className={`grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 px-4 py-6 sm:grid-cols-[2.5rem_minmax(0,1fr)] sm:px-7 ${index ? 'border-t border-rule' : ''} ${riskBorder(theme.revenue_at_risk)}`}
    >
      <span className="tnum pt-0.5 text-[22px] font-semibold leading-none text-faint" aria-label={`Rank ${rank}`}>{rank}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <div className="flex items-baseline gap-2">
            <h3 className="text-[16px] font-semibold leading-snug text-ink">{theme.title}</h3>
            {verdict && (
              <span className="rounded bg-paper px-1.5 py-0.5 text-[11px] font-medium text-muted">{verdict}</span>
            )}
          </div>
          {typeof theme.priority_score === 'number' && <span className="tnum text-[13px] text-muted"><span className="text-[20px] font-semibold text-ink">{Math.round(theme.priority_score)}</span> / 100</span>}
        </div>
        <p className="mt-1 max-w-[70ch] text-muted">{theme.summary}</p>

        {/* Mention + source count metadata */}
        {!theme.score_breakdown && <p className="mt-1 text-[13px] text-muted">{plural(theme.mention_count || 0, 'mention')} from {plural(theme.source_count || 0, 'source')}{theme.revenue_at_risk > 0 ? `, $${theme.revenue_at_risk.toLocaleString('en-US')} a year at risk` : ''}. Analyze again to see how it ranks.</p>}
        {theme.score_breakdown && (theme.mention_count || theme.source_count) ? (
          <p className="mt-1 flex items-center gap-2 text-[12px] text-faint">
            <span>{plural(theme.mention_count || 0, 'mention')}</span>
            <span aria-hidden="true">·</span>
            <span>{plural(theme.source_count || 0, 'source')}</span>
            {theme.revenue_at_risk > 0 && <>
              <span aria-hidden="true">·</span>
              <span className="font-medium">${theme.revenue_at_risk.toLocaleString('en-US')}/yr at risk</span>
            </>}
          </p>
        ) : null}

        {quote && (
          <figure className="mt-4 max-w-[68ch]">
            <blockquote className="quote">&ldquo;<span className="marked">{quote.quote_text}</span>&rdquo;</blockquote>
            <figcaption className="mt-1.5 text-[13px] text-muted">{whoSaid(quote)}{moreQuotes > 0 ? `, and ${plural(moreQuotes, 'more verified quote')}` : ''}</figcaption>
          </figure>
        )}
        <ScoreStrip breakdown={theme.score_breakdown}/>
        <div className="mt-4 flex flex-wrap items-center gap-x-1.5 gap-y-2">
          {demoLocked
            ? <button onClick={() => onApprove(theme)} disabled={Boolean(working)} title="Shows the PRD Motif would write; nothing is saved" className="btn">{working === theme.id && <LoaderCircle size={14} className="animate-spin"/>} Preview PRD</button>
            : <button onClick={() => onApprove(theme)} disabled={Boolean(working) || !canEdit} title="Writes the PRD and opens a GitHub issue" className="btn">{working === theme.id ? <LoaderCircle size={14} className="animate-spin"/> : <Check size={14}/>} Approve</button>}
          <button onClick={() => onOpenEvidence(theme)} className="btn-text">Open evidence</button>
          {!demoLocked && <button onClick={() => onReject(theme)} disabled={Boolean(working) || !canEdit} className="btn-danger">Reject</button>}
          {last && <span className="w-full text-[13px] text-muted sm:ml-auto sm:w-auto" data-testid="theme-activity">{describeActivity(last)}</span>}
        </div>
      </div>
    </li>
  );
}
