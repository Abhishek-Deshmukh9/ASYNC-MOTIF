'use client';

import type { EvalMetrics } from '@/utils/types';

const pct = (value: number | null | undefined) => (value === null || value === undefined ? '—' : `${value}%`);
const meets = (value: number | null | undefined, target: number) => value !== null && value !== undefined && value >= target;
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;

type MetricCell = {
  label: string;
  value: string;
  target: string;
  met: boolean;
  measured: boolean;
  sub: string;
  riskTier?: 'critical' | 'moderate' | 'low';
};

function riskTier(amount: number): 'critical' | 'moderate' | 'low' {
  if (amount >= 100_000) return 'critical';
  if (amount >= 10_000) return 'moderate';
  return 'low';
}

const RISK_STYLES: Record<string, string> = {
  critical: 'text-danger',
  moderate: 'text-caution',
  low: 'text-action',
};

type Props = {
  metrics: EvalMetrics | null;
  lastRunSeconds: number | null;
  isDemo: boolean;
};

export default function MetricStrip({ metrics, lastRunSeconds, isDemo }: Props) {
  const cells: MetricCell[] = isDemo
    ? [
        { label: 'Theme precision (top 3)', value: pct(metrics?.precision_at_3), target: '90% or more', met: meets(metrics?.precision_at_3, 90), measured: metrics?.precision_at_3 != null, sub: metrics?.precision_at_3 == null ? 'Measured after the first analysis' : 'Top 3 themes against the true top 3' },
        { label: 'Approved without edits', value: pct(metrics?.acceptance_rate), target: '70% or more', met: meets(metrics?.acceptance_rate, 70), measured: metrics?.acceptance_rate != null, sub: metrics?.acceptance_rate == null ? 'No decisions yet' : `Across ${plural(metrics!.pm_decisions_count, 'decision')}` },
        { label: 'Quotes verified', value: pct(metrics?.citation_validity), target: '100%', met: meets(metrics?.citation_validity, 100), measured: metrics?.citation_validity != null, sub: metrics?.citation_validity == null ? 'No quotes stored yet' : `${metrics!.verified_quotes_count} of ${metrics!.total_quotes_count} found word for word` },
        { label: 'Analysis time', value: lastRunSeconds === null ? '—' : `${lastRunSeconds}s`, target: 'under 90s', met: lastRunSeconds !== null && lastRunSeconds < 90, measured: lastRunSeconds !== null, sub: lastRunSeconds === null ? 'Shown after the next analysis' : 'Last run, start to ranked themes' },
        { label: 'Revenue at risk', value: metrics ? `$${Math.round(metrics.total_revenue_at_risk / 1000).toLocaleString('en-US')}k` : '—', target: '', met: false, measured: Boolean(metrics), sub: `Across ${plural(metrics?.total_themes_discovered ?? 0, 'theme')}, each account once`, riskTier: metrics ? riskTier(metrics.total_revenue_at_risk) : undefined },
      ]
    : [
        { label: 'Themes to review', value: metrics ? `${metrics.pending_themes_count}` : '—', target: '', met: false, measured: Boolean(metrics), sub: `${metrics?.total_themes_discovered ?? 0} discovered total` },
        { label: 'Approved', value: metrics ? `${metrics.approved_themes_count}` : '—', target: '', met: false, measured: Boolean(metrics), sub: metrics?.rejected_themes_count ? `${metrics.rejected_themes_count} rejected` : 'None rejected' },
        { label: 'Revenue at risk', value: metrics ? `$${Math.round(metrics.total_revenue_at_risk / 1000).toLocaleString('en-US')}k` : '—', target: '', met: false, measured: Boolean(metrics), sub: `Across ${plural(metrics?.total_themes_discovered ?? 0, 'theme')}`, riskTier: metrics ? riskTier(metrics.total_revenue_at_risk) : undefined },
        { label: 'Quotes verified', value: pct(metrics?.citation_validity), target: '100%', met: meets(metrics?.citation_validity, 100), measured: metrics?.citation_validity != null, sub: metrics?.citation_validity == null ? 'No quotes yet' : `${metrics!.verified_quotes_count} of ${metrics!.total_quotes_count}` },
        { label: 'Feedback items', value: metrics ? `${metrics.total_feedback_items}` : '—', target: '', met: false, measured: Boolean(metrics), sub: 'Passages across all sources' },
      ];

  return (
    <dl className={`grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-rule bg-rule sm:grid-cols-2 ${isDemo ? 'lg:grid-cols-5' : 'lg:grid-cols-5'}`}>
      {cells.map((cell) => (
        <div key={cell.label} className="bg-surface px-4 py-3.5">
          <dt className="text-[13px] text-muted">{cell.label}</dt>
          <dd className={`tnum mt-1 text-[24px] font-semibold leading-tight ${cell.riskTier ? RISK_STYLES[cell.riskTier] : 'text-ink'}`}>{cell.value}</dd>
          {cell.target && <dd className={`text-[12px] font-medium ${!cell.measured ? 'text-muted' : cell.met ? 'text-action' : 'text-caution'}`}>Target {cell.target}{cell.measured ? (cell.met ? ', met' : ', not yet') : ''}</dd>}
          <dd className="text-[12px] leading-snug text-muted">{cell.sub}</dd>
        </div>
      ))}
    </dl>
  );
}
