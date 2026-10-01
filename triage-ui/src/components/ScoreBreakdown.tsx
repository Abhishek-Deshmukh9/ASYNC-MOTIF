'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { ScoreBreakdown as Breakdown, ScoreSignal } from '@/utils/types';

// Same order on every theme so a PM can compare down the list
const ORDER = ['reach', 'revenue', 'urgency', 'breadth', 'momentum', 'strategic'];
// The letter each parameter goes by in the formula
const SYMBOLS: Record<string, string> = { reach: 'R', revenue: 'V', urgency: 'U', breadth: 'S', momentum: 'M', strategic: 'E' };
const pts = (n: number) => (Math.abs(n - Math.round(n)) < 0.05 ? Math.round(n).toString() : n.toFixed(1));

type Row = Record<string, unknown>;
const text = (value: unknown) => (typeof value === 'string' || typeof value === 'number' ? String(value) : '');

function evidenceLine(key: string, row: Row): string {
  const name = text(row.name);
  const mentions = (n: unknown) => `${text(n)} mention${n === 1 ? '' : 's'}`;
  switch (key) {
    case 'reach': return `${name}, ${mentions(row.mentions)}`;
    case 'revenue': return `${name}${row.tier ? ` (${text(row.tier)})` : ''}: $${Number(row.arr ?? 0).toLocaleString('en-US')} a year`;
    case 'urgency': return `${name}: “${text(row.text)}”`;
    case 'breadth': return `${name}, ${mentions(row.mentions)}`;
    case 'momentum': return `${name}: ${text(row.mentions)}`;
    default: return name;
  }
}

/** The parameters behind a theme's rank, as a small table: what the data says and the points it earned. */
export function ScoreStrip({ breakdown }: { breakdown?: Breakdown | null; score?: number | null }) {
  if (!breakdown) return null;
  const top = [...breakdown.signals].sort((a, b) => b.points - a.points)[0];
  return (
    <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-rule bg-rule sm:grid-cols-3" data-testid="score-strip">
      {ORDER.map((key) => {
        const signal = breakdown.signals.find((item) => item.key === key);
        if (signal) {
          const max = signal.max_points ?? signal.weight * 100;
          const isTop = top && top.key === key && signal.points > 0;
          return (
            <div key={key} data-testid={`param-${key}`} title={signal.how} className={`bg-surface px-3 py-2.5 ${isTop ? 'shadow-[inset_0_2px_0_var(--color-action)]' : ''}`}>
              <dt className="flex items-baseline justify-between gap-2 text-[12px] text-muted">
                <span>{signal.label}</span>
                {isTop && <span className="text-[11px] font-medium text-action">biggest factor</span>}
              </dt>
              <dd className="mt-0.5 truncate text-[15px] font-semibold text-ink">{signal.value ?? signal.display}</dd>
              {signal.note && <dd className="line-clamp-2 text-[12px] leading-snug text-muted">{signal.note}</dd>}
              <dd className="mt-1 text-[12px] text-ink"><span className="font-semibold">+{pts(signal.points)}</span><span className="text-muted"> of {pts(max)}</span></dd>
            </div>
          );
        }
        const dropped = breakdown.dropped.find((item) => item.key === key);
        if (!dropped) return null;
        return (
          <div key={key} data-testid={`param-${key}`} title={dropped.reason} className="bg-paper px-3 py-2.5">
            <dt className="text-[12px] text-muted">{dropped.label}</dt>
            <dd className="mt-0.5 text-[14px] font-medium text-faint">Not used</dd>
            <dd className="text-[12px] leading-snug text-muted">{dropped.short ?? dropped.reason}</dd>
          </div>
        );
      })}
    </dl>
  );
}

/** One expandable line above the list: what the ranking depends on and how much each part can add. */
export function RankingKey({ breakdown }: { breakdown?: Breakdown | null }) {
  if (!breakdown) return null;
  const used = ORDER.map((key) => breakdown.signals.find((item) => item.key === key)).filter(Boolean) as ScoreSignal[];
  return (
    <details className="group border-b border-rule px-5 py-3.5 text-[13px] text-muted sm:px-7" data-testid="ranking-key">
      <summary className="flex cursor-pointer list-none items-start gap-1.5 text-ink marker:hidden">
        <ChevronRight size={15} className="mt-0.5 shrink-0 text-muted transition-transform group-open:rotate-90"/>
        <span>
          Ranked for {breakdown.profile_label} by{' '}
          {used.map((signal, index) => (
            <span key={signal.key}>
              {signal.label.toLowerCase()} <span className="tnum text-muted">({pts(signal.max_points ?? signal.weight * 100)})</span>
              {index < used.length - 2 ? ', ' : index === used.length - 2 ? ' and ' : ''}
            </span>
          ))}
          . The numbers in brackets are the most points each can add.
        </span>
      </summary>
      <div className="mt-3 max-w-[72ch] space-y-2 pl-6 leading-relaxed">
        <p>Each parameter earns its points by how a theme compares with the other {breakdown.of - 1} theme{breakdown.of === 2 ? '' : 's'} in this project: the highest gets the full amount, the lowest gets none, and a theme with none of something (no churn talk, a falling trend) gets nothing for it. The points add up to the score out of 100.</p>
        {breakdown.dropped.length > 0 && (
          <p>Not used here: {breakdown.dropped.map((item) => `${item.label.toLowerCase()} (${item.short ?? item.reason})`).join(', ')}. Their points were shared among the others.</p>
        )}
        <p>Open a theme to see the customers, quotes and sources behind every number, and the formula with its own values.</p>
      </div>
    </details>
  );
}

function SignalRow({ signal }: { signal: ScoreSignal }) {
  const [open, setOpen] = useState(false);
  const max = signal.max_points ?? signal.weight * 100;
  return (
    <li className="border-b border-rule last:border-b-0">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 py-2.5 text-left">
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-semibold text-ink">{signal.label}</span>
          <span className="block text-[13px] text-muted">{signal.display}</span>
        </span>
        <span className="tnum shrink-0 text-[13px] text-ink"><span className="font-semibold">+{pts(signal.points)}</span><span className="text-muted"> of {pts(max)}</span></span>
        {open ? <ChevronDown size={15} className="shrink-0 text-muted"/> : <ChevronRight size={15} className="shrink-0 text-muted"/>}
      </button>
      {open && (
        <div className="space-y-3 pb-3.5 text-[13px] leading-relaxed text-muted">
          <div>
            <p className="font-medium text-ink">From your data</p>
            {signal.evidence.length ? (
              <ul className="mt-1 list-disc space-y-0.5 pl-5">{signal.evidence.map((row, index) => <li key={index} className="break-words">{evidenceLine(signal.key, row as Row)}</li>)}</ul>
            ) : <p className="mt-1">Nothing in this theme for this parameter.</p>}
          </div>
          <div><p className="font-medium text-ink">Why it counts</p><p>{signal.why}</p></div>
          <div><p className="font-medium text-ink">How it is worked out</p><p>{signal.how}</p></div>
        </div>
      )}
    </li>
  );
}

/** The score written out as maths, then again with this theme's numbers plugged in. */
function Formula({ breakdown }: { breakdown: Breakdown }) {
  const terms = breakdown.signals;
  const total = terms.reduce((sum, s) => sum + s.points, 0);
  const line = (lead: string, parts: string[]) => (
    <div className="flex flex-wrap gap-x-1">
      <span className="whitespace-nowrap">{lead} 100 × (</span>
      {parts.map((part, index) => <span key={index} className="whitespace-nowrap">{part}{index < parts.length - 1 ? ' +' : ')'}</span>)}
    </div>
  );
  return (
    <div className="mt-4 rounded-md bg-paper px-4 py-3.5 text-[13px] text-ink" data-testid="score-formula">
      <p className="font-semibold">The formula</p>
      <div className="tnum mt-2 space-y-1">
        {line('Score =', terms.map((s) => `${s.weight.toFixed(2)}·${SYMBOLS[s.key] ?? s.key}̂`))}
        {line('=', terms.map((s) => `${s.weight.toFixed(2)}×${s.percentile.toFixed(2)}`))}
        <div className="font-semibold">= {total.toFixed(1)}</div>
      </div>
      <p className="mt-2.5 text-[12px] leading-relaxed text-muted">
        {terms.map((s) => `${SYMBOLS[s.key]}̂ is ${s.label.toLowerCase()}`).join(', ')}. Each is this theme&apos;s position among the {breakdown.of} themes, from 0 (lowest) to 1 (highest); none of something counts as 0.
        {breakdown.dropped.length > 0 && <> Weights were rescaled to add up to 1 because {breakdown.dropped.map((d) => d.label.toLowerCase()).join(' and ')} could not be worked out.</>}
      </p>
    </div>
  );
}

/** Full explanation for the review dialog: every parameter with its proof, what was left out and why. */
export function ScoreProof({ breakdown }: { breakdown?: Breakdown | null }) {
  if (!breakdown) return null;
  const thin = breakdown.confidence.level === 'thin';
  return (
    <section className="mt-6" aria-label="Why this theme ranked here" data-testid="score-proof">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[15px] font-semibold text-ink">Why it ranked {breakdown.rank} of {breakdown.of}</h3>
        <span className="tnum text-[13px] text-muted"><span className="text-[17px] font-semibold text-ink">{pts(breakdown.priority_score)}</span> / 100</span>
      </div>
      <ul className="mt-2">{breakdown.signals.map((signal) => <SignalRow key={signal.key} signal={signal} />)}</ul>
      {breakdown.dropped.length > 0 && (
        <p className="mt-3 text-[13px] leading-relaxed text-muted">Not used for this project: {breakdown.dropped.map((item) => `${item.label.toLowerCase()} (${item.reason.replace(/\.$/, '').toLowerCase()})`).join('; ')}.</p>
      )}
      <Formula breakdown={breakdown} />
      <p className={`mt-3 text-[13px] leading-relaxed ${thin ? 'text-caution' : 'text-muted'}`}>
        {thin ? 'Thin evidence: ' : 'Evidence: '}{breakdown.confidence.verified_quotes} message{breakdown.confidence.verified_quotes === 1 ? '' : 's'} with a verified quote out of {breakdown.confidence.mentions}. Ranking profile: {breakdown.profile_label}. The weights are product choices, shown with every score; no AI model sets a number here.
      </p>
    </section>
  );
}
