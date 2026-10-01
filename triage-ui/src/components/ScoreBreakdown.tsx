'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Info, ShieldCheck, TriangleAlert } from 'lucide-react';
import type { ScoreBreakdown as Breakdown, ScoreSignal } from '@/utils/types';

// One colour per signal, used in the bar and next to each row so the two read together
const COLORS: Record<string, string> = {
  reach: 'bg-teal-600',
  revenue: 'bg-emerald-500',
  urgency: 'bg-rose-500',
  breadth: 'bg-sky-500',
  momentum: 'bg-amber-500',
  strategic: 'bg-violet-500',
};
const color = (key: string) => COLORS[key] ?? 'bg-slate-400';

type Row = Record<string, unknown>;
const text = (value: unknown) => (typeof value === 'string' || typeof value === 'number' ? String(value) : '');

function evidenceLine(key: string, row: Row): string {
  const name = text(row.name);
  switch (key) {
    case 'reach': return `${name} · ${text(row.kind)} · ${text(row.mentions)} mention${row.mentions === 1 ? '' : 's'}`;
    case 'revenue': return `${name}${row.tier ? ` · ${text(row.tier)}` : ''} · $${Number(row.arr ?? 0).toLocaleString('en-US')} ARR`;
    case 'urgency': return `${name}: “${text(row.text)}”`;
    case 'breadth': return `${name} · ${text(row.mentions)} mention${row.mentions === 1 ? '' : 's'}`;
    case 'momentum': return `${name}: ${text(row.mentions)}`;
    default: return name;
  }
}

// Same order on every card so a PM can compare themes down the list
const ORDER = ['reach', 'revenue', 'urgency', 'breadth', 'momentum', 'strategic'];
const pts = (n: number) => (Math.abs(n - Math.round(n)) < 0.05 ? Math.round(n).toString() : n.toFixed(1));

/** Every parameter behind a theme's rank, written out: its value from the data and the points it earned. */
export function ScoreStrip({ breakdown, score }: { breakdown?: Breakdown | null; score?: number | null }) {
  if (!breakdown) return null;
  const top = [...breakdown.signals].sort((a, b) => b.points - a.points)[0];
  const thin = breakdown.confidence.level === 'thin';
  return (
    <div className="mt-3" data-testid="score-strip">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[11px]">
        <span className="font-semibold text-slate-900">Score {pts(score ?? breakdown.priority_score)} / 100</span>
        <span className="text-slate-400">ranked #{breakdown.rank} of {breakdown.of}</span>
        {thin && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-800" title="Fewer than 2 messages contain a verified quote, or fewer than 3 mentions">Thin evidence</span>}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-3">
        {ORDER.map((key) => {
          const signal = breakdown.signals.find((item) => item.key === key);
          if (signal) {
            const max = signal.max_points ?? signal.weight * 100;
            const isTop = top && top.key === key && signal.points > 0;
            return (
              <div key={key} data-testid={`param-${key}`} title={`${signal.label}: ${signal.display}. ${signal.how}`} className={`rounded-lg border px-2.5 py-2 ${isTop ? 'border-teal-600 bg-teal-50/60' : 'border-slate-200 bg-white'}`}>
                <div className="flex flex-wrap items-center justify-between gap-x-1">
                  <span className="text-[9px] font-semibold uppercase tracking-[.12em] text-slate-500">{signal.label}</span>
                  {isTop && <span className="text-[9px] font-medium text-teal-700">top factor</span>}
                </div>
                <div className="mt-1 truncate text-sm font-semibold text-slate-900">{signal.value ?? signal.display}</div>
                {signal.note && <div className="line-clamp-2 text-[10px] leading-4 text-slate-500">{signal.note}</div>}
                <div className="mt-1.5 font-mono text-[10px] text-slate-700"><span className="font-semibold">+{pts(signal.points)}</span><span className="text-slate-400"> of {pts(max)} pts</span></div>
              </div>
            );
          }
          const dropped = breakdown.dropped.find((item) => item.key === key);
          if (!dropped) return null;
          return (
            <div key={key} data-testid={`param-${key}`} title={dropped.reason} className="rounded-lg border border-dashed border-slate-200 px-2.5 py-2 text-slate-400">
              <div className="text-[9px] font-semibold uppercase tracking-[.12em]">{dropped.label}</div>
              <div className="mt-1 text-[12px] font-medium">Not used</div>
              <div className="text-[10px] leading-4">{dropped.short ?? dropped.reason}</div>
              <div className="mt-1.5 font-mono text-[10px]">0 pts</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** One line above the list: what the ranking depends on and how much each part can add. */
export function RankingKey({ breakdown }: { breakdown?: Breakdown | null }) {
  if (!breakdown) return null;
  return (
    <div className="border-b border-slate-200 bg-slate-50/70 px-5 py-3 text-[11px] leading-5 text-slate-600 sm:px-6" data-testid="ranking-key">
      <div><span className="font-semibold text-slate-800">How themes are ranked</span> <span className="text-slate-400">({breakdown.profile_label})</span>: the score out of 100 adds up these parameters.</div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {ORDER.map((key) => {
          const signal = breakdown.signals.find((item) => item.key === key);
          if (signal) return <span key={key} className="rounded-full border border-slate-200 bg-white px-2 py-0.5">{signal.label} <span className="font-mono text-slate-500">up to {pts(signal.max_points ?? signal.weight * 100)}</span></span>;
          const dropped = breakdown.dropped.find((item) => item.key === key);
          return dropped ? <span key={key} title={dropped.reason} className="rounded-full border border-dashed border-slate-200 px-2 py-0.5 text-slate-400">{dropped.label}: not used, {dropped.short ?? 'no data'}</span> : null;
        })}
      </div>
      <p className="mt-1.5 text-[10px] text-slate-500">Each parameter earns its points by how the theme compares with the rest of the {breakdown.of} themes in this project: the highest gets the full amount, the lowest gets none, and a theme with none of something (no churn talk, a falling trend) gets 0 for it. Open Review &amp; edit for the proof behind each number and the formula.</p>
    </div>
  );
}

function SignalRow({ signal }: { signal: ScoreSignal }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-slate-200 bg-white">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 px-3 py-2.5 text-left">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color(signal.key)}`} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] font-semibold text-slate-800">{signal.label}</span>
            <span className="font-mono text-[10px] text-slate-500">+{signal.points.toFixed(1)} <span className="text-slate-300">/ {(signal.weight * 100).toFixed(0)}</span></span>
          </span>
          <span className="mt-0.5 block text-[11px] text-slate-600">{signal.display}</span>
          <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-slate-100"><span className={`block h-full ${color(signal.key)}`} style={{ width: `${Math.round(signal.percentile * 100)}%` }} /></span>
        </span>
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-400" /> : <ChevronRight size={14} className="shrink-0 text-slate-400" />}
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 px-3 py-3 text-[11px] leading-5 text-slate-600">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-400">Proof from your data</div>
            {signal.evidence.length ? (
              <ul className="mt-1 space-y-1">{signal.evidence.map((row, index) => <li key={index} className="break-words rounded bg-slate-50 px-2 py-1">{evidenceLine(signal.key, row as Row)}</li>)}</ul>
            ) : <p className="mt-1 text-slate-400">No rows to show: this theme has none for this signal.</p>}
          </div>
          <div><div className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-400">Why this signal</div><p className="mt-0.5">{signal.why}</p></div>
          <div><div className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-400">How it is computed</div><p className="mt-0.5">{signal.how}</p></div>
        </div>
      )}
    </li>
  );
}

// The letter each signal goes by in the formula
const SYMBOLS: Record<string, string> = { reach: 'R', revenue: 'V', urgency: 'U', breadth: 'S', momentum: 'M', strategic: 'E' };

/** The score written out as maths, then again with this theme's numbers plugged in. */
function Formula({ breakdown }: { breakdown: Breakdown }) {
  const terms = breakdown.signals;
  const symbolic = terms.map((s) => `${s.weight.toFixed(2)}·${SYMBOLS[s.key] ?? s.key}\u0302`);
  const plugged = terms.map((s) => `${s.weight.toFixed(2)}×${s.percentile.toFixed(2)}`);
  // Each term stays on one line; lines break between terms so nothing is cut off on narrow screens
  const line = (lead: string, parts: string[], className = '') => (
    <div className={`flex flex-wrap gap-x-1 ${className}`}>
      <span className="whitespace-nowrap">{lead} 100 × (</span>
      {parts.map((part, index) => <span key={index} className="whitespace-nowrap">{part}{index < parts.length - 1 ? ' +' : ')'}</span>)}
    </div>
  );
  const total = terms.reduce((sum, s) => sum + s.points, 0);
  return (
    <div className="mt-3 rounded-lg bg-slate-900 px-3 py-3 text-slate-100" data-testid="score-formula">
      <div className="text-[10px] font-semibold uppercase tracking-[.14em] text-slate-400">The maths</div>
      <div className="mt-2 space-y-1.5 font-mono text-[11px] leading-5">
        {line('Score =', symbolic)}
        {line('=', plugged, 'text-slate-300')}
        <div className="font-semibold">= {total.toFixed(1)}</div>
      </div>
      <ul className="mt-2 grid grid-cols-1 gap-x-4 text-[10px] leading-4 text-slate-400 sm:grid-cols-2">
        {terms.map((s) => <li key={s.key}><span className="font-mono text-slate-200">{SYMBOLS[s.key]}̂</span> = {s.label} ({s.display})</li>)}
      </ul>
      <p className="mt-2 text-[10px] leading-4 text-slate-400">
        Each value x̂ = (rank of this theme&apos;s value − 1) ÷ (N − 1) among the {breakdown.of} themes in this project, so 0 is the lowest and 1 the highest; ties share their average rank, and a value of zero scores 0.
        {breakdown.dropped.length > 0 && <> Weights were rescaled to add up to 1 because {breakdown.dropped.map((d) => d.label.toLowerCase()).join(', ')} could not be computed.</>}
      </p>
    </div>
  );
}

/** Full explanation for the review dialog: every signal with its proof, what was left out and why. */
export function ScoreProof({ breakdown }: { breakdown?: Breakdown | null }) {
  if (!breakdown) return null;
  const thin = breakdown.confidence.level === 'thin';
  return (
    <section className="mt-5" aria-label="Why this theme ranked here" data-testid="score-proof">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[.16em] text-slate-500">Why it ranked #{breakdown.rank} of {breakdown.of}</h3>
        <span className="font-mono text-xs font-semibold text-slate-900">{breakdown.priority_score.toFixed(0)}<span className="text-slate-400"> / 100</span></span>
      </div>
      <p className="mt-1 text-[11px] leading-5 text-slate-600">{breakdown.verdict}</p>
      <ul className="mt-3 space-y-2">{breakdown.signals.map((signal) => <SignalRow key={signal.key} signal={signal} />)}</ul>

      <Formula breakdown={breakdown} />

      {breakdown.dropped.length > 0 && (
        <div className="mt-3 rounded-lg border border-dashed border-slate-300 px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[.14em] text-slate-400"><Info size={11} /> Not used for this project</div>
          <ul className="mt-1.5 space-y-1 text-[11px] leading-5 text-slate-600">{breakdown.dropped.map((item) => <li key={item.key}><span className="font-medium text-slate-700">{item.label}:</span> {item.reason}</li>)}</ul>
        </div>
      )}

      <div className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2.5 text-[11px] leading-5 ${thin ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-900'}`}>
        {thin ? <TriangleAlert size={13} className="mt-0.5 shrink-0" /> : <ShieldCheck size={13} className="mt-0.5 shrink-0" />}
        <span>{thin ? 'Thin evidence: ' : 'Well supported: '}{breakdown.confidence.verified_quotes} verified quote{breakdown.confidence.verified_quotes === 1 ? '' : 's'} across {breakdown.confidence.mentions} mentions; cluster cohesion {breakdown.confidence.cohesion.toFixed(2)}.</span>
      </div>
      <p className="mt-2 text-[10px] leading-4 text-slate-400">Ranking profile: {breakdown.profile_label}. Weights are product choices shown with every score, not measured constants; no AI model sets a number here.</p>
    </section>
  );
}
