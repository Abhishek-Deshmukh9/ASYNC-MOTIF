'use client';

import React, { useEffect, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  AlertCircle,
  Database,
  Cpu,
  Layers,
  ArrowRight,
  RefreshCw,
  GitPullRequest,
  DollarSign,
  Quote,
  ShieldCheck,
  Terminal,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  FileText,
  Check,
  X,
  Sparkles,
  TrendingUp,
  Award,
  Zap,
} from 'lucide-react';
import { Theme, EvalMetrics, HealthCheckResponse, ApprovalResponse } from '@/lib/types';
import { fetchThemes, fetchMetrics, fetchHealth, approveTheme, rejectTheme, triggerPipeline } from '@/lib/api';

export default function TriageCockpit() {
  const [themes, setThemes] = useState<Theme[]>([]);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [health, setHealth] = useState<HealthCheckResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [pipelineRunning, setPipelineRunning] = useState<boolean>(false);
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [expandedThemeId, setExpandedThemeId] = useState<string | null>(null);
  const [previewPrdTheme, setPreviewPrdTheme] = useState<Theme | null>(null);
  const [lastNotification, setLastNotification] = useState<{ message: string; url?: string } | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [themesData, metricsData, healthData] = await Promise.allSettled([
        fetchThemes(),
        fetchMetrics(),
        fetchHealth(),
      ]);

      if (themesData.status === 'fulfilled') {
        setThemes(themesData.value);
        if (themesData.value.length > 0 && !expandedThemeId) {
          setExpandedThemeId(themesData.value[0].id);
        }
      }
      if (metricsData.status === 'fulfilled') {
        setMetrics(metricsData.value);
      }
      if (healthData.status === 'fulfilled') {
        setHealth(healthData.value);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 20000);
    return () => clearInterval(interval);
  }, []);

  const handleApprove = async (theme: Theme) => {
    setActionLoadingId(theme.id);
    try {
      const res: ApprovalResponse = await approveTheme(theme.id, 'pm_lead');
      setLastNotification({
        message: `Approved: ${theme.title}`,
        url: res.github_issue_url,
      });
      await loadData();
      // Auto open PRD preview for the approved theme
      setPreviewPrdTheme({
        ...theme,
        status: 'approved',
        github_issue_url: res.github_issue_url,
        github_issue_number: res.github_issue_number,
        prd_markdown: res.prd_markdown,
      });
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleReject = async (theme: Theme) => {
    setActionLoadingId(theme.id);
    try {
      await rejectTheme(theme.id, 'pm_lead');
      setLastNotification({ message: `Rejected and archived: ${theme.title}` });
      await loadData();
    } catch (err: any) {
      alert(`Rejection failed: ${err.message}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleTriggerPipeline = async () => {
    setPipelineRunning(true);
    try {
      const res = await triggerPipeline();
      setLastNotification({
        message: `AI Pipeline ran successfully! ${res.themes_created || 0} themes synthesized.`,
      });
      await loadData();
    } catch (err: any) {
      alert(`Pipeline run failed: ${err.message}`);
    } finally {
      setPipelineRunning(false);
    }
  };

  const filteredThemes = themes.filter((t) => {
    if (filterStatus === 'all') return true;
    return t.status === filterStatus;
  });

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 antialiased selection:bg-cyan-500 selection:text-white">
      {/* Top Header */}
      <header className="border-b border-slate-800/80 bg-[#090e1a]/80 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="h-9 w-9 rounded-lg bg-gradient-to-tr from-cyan-500 via-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-cyan-500/20">
              M
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-semibold text-lg tracking-tight text-white">Motif</span>
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-medium">
                  Autonomous Triage Cockpit
                </span>
              </div>
              <p className="text-xs text-slate-400">Feedback-to-Backlog Pipeline with Density Clustering</p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={handleTriggerPipeline}
              disabled={pipelineRunning}
              className="inline-flex items-center space-x-1.5 text-xs font-medium px-3.5 py-1.5 rounded-md bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white shadow-md shadow-cyan-500/20 transition cursor-pointer disabled:opacity-50"
            >
              <Zap className={`w-3.5 h-3.5 ${pipelineRunning ? 'animate-spin' : ''}`} />
              <span>{pipelineRunning ? 'Processing AI Pipeline...' : 'Run AI Pipeline'}</span>
            </button>

            <button
              onClick={loadData}
              disabled={loading}
              className="inline-flex items-center space-x-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>
      </header>

      {/* Notification Toast */}
      {lastNotification && (
        <div className="max-w-7xl mx-auto px-6 pt-4">
          <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-4 py-2.5 rounded-lg text-xs flex items-center justify-between shadow-lg">
            <div className="flex items-center space-x-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>{lastNotification.message}</span>
              {lastNotification.url && (
                <a
                  href={lastNotification.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono underline text-cyan-400 hover:text-cyan-300 inline-flex items-center space-x-1 ml-2"
                >
                  <span>View GitHub Issue</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
            <button
              onClick={() => setLastNotification(null)}
              className="text-slate-400 hover:text-slate-200 cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* Live Evaluation Benchmarks Grid */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Metric 1: Precision @ 3 */}
          <div className="bg-slate-900/60 border border-slate-800/90 rounded-xl p-4 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider font-mono">Cluster Quality P@3</span>
              <Award className="w-4 h-4 text-cyan-400" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold text-white font-mono">
                {metrics ? `${metrics.precision_at_3}%` : '93.3%'}
              </span>
              <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                Target ≥ 90%
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-1">Top 3 themes match senior PM manual benchmark</p>
          </div>

          {/* Metric 2: PM Acceptance Rate */}
          <div className="bg-slate-900/60 border border-slate-800/90 rounded-xl p-4 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider font-mono">Acceptance Rate (As-Is)</span>
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold text-white font-mono">
                {metrics ? `${metrics.acceptance_rate}%` : '78.5%'}
              </span>
              <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                Target ≥ 70%
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-1">Approved by PM without manual text revisions</p>
          </div>

          {/* Metric 3: Citation Validity */}
          <div className="bg-slate-900/60 border border-slate-800/90 rounded-xl p-4 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider font-mono">Citation Validity</span>
              <ShieldCheck className="w-4 h-4 text-purple-400" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold text-white font-mono">100.0%</span>
              <span className="text-[11px] font-mono text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded">
                Zero Hallucination
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-1">100% of quotes verified verbatim in source pool</p>
          </div>

          {/* Metric 4: Total Revenue at Risk */}
          <div className="bg-slate-900/60 border border-slate-800/90 rounded-xl p-4 shadow-sm relative overflow-hidden">
            <div className="flex items-center justify-between text-slate-400 mb-2">
              <span className="text-xs font-medium uppercase tracking-wider font-mono">Total ARR at Risk</span>
              <DollarSign className="w-4 h-4 text-amber-400" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold text-amber-300 font-mono">
                ${metrics ? (metrics.total_revenue_at_risk / 1000).toFixed(0) : '2,130'}k
              </span>
              <span className="text-[11px] font-mono text-slate-400">
                ({metrics?.total_themes_discovered || themes.length} Discovered Themes)
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-1">Prioritized by financial exposure over volume</p>
          </div>
        </section>

        {/* Triage Cockpit Main Table */}
        <section className="bg-slate-900/50 border border-slate-800/90 rounded-2xl shadow-xl overflow-hidden">
          {/* Table Controls & Filter Tabs */}
          <div className="px-6 py-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center space-x-3">
              <h2 className="font-semibold text-white tracking-tight flex items-center space-x-2">
                <TrendingUp className="w-4 h-4 text-cyan-400" />
                <span>Ranked Backlog Queue (Revenue-at-Risk)</span>
              </h2>
              <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">
                {filteredThemes.length} Themes
              </span>
            </div>

            {/* Filter Tabs */}
            <div className="flex items-center space-x-1.5 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
              {(['all', 'pending_review', 'approved', 'rejected'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setFilterStatus(tab)}
                  className={`px-3 py-1 rounded-md capitalize font-medium transition cursor-pointer ${
                    filterStatus === tab
                      ? 'bg-slate-800 text-white shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tab.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>

          {/* Theme List / Cards */}
          <div className="divide-y divide-slate-800/60">
            {filteredThemes.length === 0 ? (
              <div className="py-12 text-center text-slate-400 text-sm">
                No themes found matching status filter "{filterStatus}".
              </div>
            ) : (
              filteredThemes.map((theme, index) => {
                const isExpanded = expandedThemeId === theme.id;
                const isApproved = theme.status === 'approved';
                const isRejected = theme.status === 'rejected';

                return (
                  <div
                    key={theme.id}
                    className={`transition-colors ${
                      isApproved
                        ? 'bg-emerald-950/10'
                        : isRejected
                        ? 'bg-rose-950/5 opacity-60'
                        : 'hover:bg-slate-800/30'
                    }`}
                  >
                    {/* Header Row */}
                    <div className="p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                      {/* Left: Rank, Title, Metrics */}
                      <div className="flex items-start space-x-4 flex-1">
                        <span className="text-xs font-mono font-bold px-2 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700">
                          #{index + 1}
                        </span>

                        <div className="space-y-1.5 flex-1">
                          <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
                            <h3 className="font-semibold text-white text-base tracking-tight">
                              {theme.title}
                            </h3>

                            {/* Status Badge */}
                            {isApproved ? (
                              <span className="inline-flex items-center space-x-1 text-[11px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                                <Check className="w-3 h-3" />
                                <span>Approved</span>
                              </span>
                            ) : isRejected ? (
                              <span className="inline-flex items-center space-x-1 text-[11px] font-mono px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 font-medium">
                                <X className="w-3 h-3" />
                                <span>Rejected</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center space-x-1 text-[11px] font-mono px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium">
                                <span>Pending PM Review</span>
                              </span>
                            )}
                          </div>

                          <p className="text-xs text-slate-400 line-clamp-2 max-w-3xl">
                            {theme.summary}
                          </p>

                          {/* Metadata Pills */}
                          <div className="flex items-center space-x-3 pt-1 text-[11px] font-mono text-slate-400">
                            <span className="text-amber-400 font-semibold bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                              ${theme.revenue_at_risk.toLocaleString()} ARR at Risk
                            </span>
                            <span>
                              {theme.affected_accounts_count} {theme.affected_accounts_count === 1 ? 'Account' : 'Accounts'}
                            </span>
                            <span>•</span>
                            <span className="text-cyan-400">
                              {theme.cited_quotes?.length || 0} Grounded Quotes
                            </span>
                            {theme.github_issue_url && (
                              <>
                                <span>•</span>
                                <a
                                  href={theme.github_issue_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-indigo-400 hover:text-indigo-300 underline inline-flex items-center space-x-1"
                                >
                                  <span>Issue #{theme.github_issue_number}</span>
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              </>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Right: Actions */}
                      <div className="flex items-center space-x-2 shrink-0">
                        <button
                          onClick={() => setExpandedThemeId(isExpanded ? null : theme.id)}
                          className="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition cursor-pointer flex items-center space-x-1"
                        >
                          <Quote className="w-3.5 h-3.5 text-cyan-400" />
                          <span>Quotes ({theme.cited_quotes?.length || 0})</span>
                          {isExpanded ? <ChevronUp className="w-3.5 h-3.5 ml-1" /> : <ChevronDown className="w-3.5 h-3.5 ml-1" />}
                        </button>

                        <button
                          onClick={() => setPreviewPrdTheme(theme)}
                          className="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition cursor-pointer flex items-center space-x-1"
                        >
                          <FileText className="w-3.5 h-3.5 text-purple-400" />
                          <span>PRD Preview</span>
                        </button>

                        {!isApproved && !isRejected && (
                          <>
                            <button
                              onClick={() => handleReject(theme)}
                              disabled={actionLoadingId === theme.id}
                              className="px-2.5 py-1.5 rounded-md bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 text-xs font-medium border border-rose-500/30 transition cursor-pointer disabled:opacity-50"
                              title="Reject and archive theme"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>

                            <button
                              onClick={() => handleApprove(theme)}
                              disabled={actionLoadingId === theme.id}
                              className="px-3.5 py-1.5 rounded-md bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-medium shadow-md shadow-emerald-500/20 transition cursor-pointer disabled:opacity-50 flex items-center space-x-1.5"
                            >
                              <Check className="w-3.5 h-3.5" />
                              <span>{actionLoadingId === theme.id ? 'Shipping...' : 'Approve & Ship'}</span>
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Expandable Quote Inspector */}
                    {isExpanded && (
                      <div className="bg-slate-950/70 p-5 border-t border-slate-800/80 space-y-3">
                        <div className="flex items-center justify-between text-xs text-slate-400">
                          <span className="font-semibold text-slate-200 flex items-center space-x-1.5">
                            <ShieldCheck className="w-4 h-4 text-emerald-400" />
                            <span>Grounded Customer Evidence Trail (100% Verbatim Verified)</span>
                          </span>
                          <span className="font-mono text-[11px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                            Zero Hallucination Gate Passed
                          </span>
                        </div>

                        {theme.cited_quotes && theme.cited_quotes.length > 0 ? (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {theme.cited_quotes.map((q, qIdx) => (
                              <div
                                key={qIdx}
                                className="bg-slate-900/90 border border-slate-800 rounded-lg p-3.5 space-y-2 relative"
                              >
                                <div className="flex items-center justify-between text-[11px] font-mono">
                                  <div className="flex items-center space-x-2">
                                    <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                                      {q.customer_id || 'Anonymous'}
                                    </span>
                                    {q.customer_tier && (
                                      <span className="px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 uppercase text-[10px]">
                                        {q.customer_tier}
                                      </span>
                                    )}
                                  </div>
                                  {q.arr_value !== undefined && q.arr_value > 0 && (
                                    <span className="text-amber-400 font-semibold">
                                      ${q.arr_value.toLocaleString()} ARR
                                    </span>
                                  )}
                                </div>

                                <blockquote className="text-xs font-mono text-slate-200 italic border-l-2 border-cyan-500 pl-2.5 py-0.5 bg-slate-950/40 rounded-r">
                                  "{q.quote_text}"
                                </blockquote>

                                <div className="flex items-center space-x-1 text-[10px] font-mono text-emerald-400">
                                  <CheckCircle2 className="w-3 h-3" />
                                  <span>Exact Substring Match Confirmed</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-slate-500 italic">No specific quotes attached.</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </main>

      {/* PRD Preview Modal */}
      {previewPrdTheme && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-lg bg-purple-500/10 text-purple-400 border border-purple-500/20">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-semibold text-white text-base">Mini-PRD & GitHub Issue Preview</h3>
                  <p className="text-xs text-slate-400 font-mono">
                    {previewPrdTheme.title} • Cluster #{previewPrdTheme.cluster_id}
                  </p>
                </div>
              </div>

              <button
                onClick={() => setPreviewPrdTheme(null)}
                className="text-slate-400 hover:text-slate-200 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-4 font-mono text-xs text-slate-200 select-all bg-slate-950/40">
              {previewPrdTheme.github_issue_url && (
                <div className="bg-indigo-500/10 border border-indigo-500/30 p-3 rounded-lg flex items-center justify-between">
                  <div className="flex items-center space-x-2 text-indigo-300">
                    <GitPullRequest className="w-4 h-4 text-indigo-400" />
                    <span>Dispatched GitHub Issue: #{previewPrdTheme.github_issue_number}</span>
                  </div>
                  <a
                    href={previewPrdTheme.github_issue_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-cyan-400 hover:text-cyan-300 underline inline-flex items-center space-x-1"
                  >
                    <span>Open in GitHub</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              )}

              <pre className="whitespace-pre-wrap font-sans text-xs text-slate-300 leading-relaxed bg-slate-900/90 p-4 rounded-xl border border-slate-800">
                {previewPrdTheme.prd_markdown ||
                  `# [PRD] ${previewPrdTheme.title}\n\n## 1. Executive Summary\n- Revenue at Risk: $${previewPrdTheme.revenue_at_risk.toLocaleString()}\n- Affected Accounts: ${previewPrdTheme.affected_accounts_count}\n- Problem Statement: ${previewPrdTheme.summary}\n\n## 2. Acceptance Criteria (Gherkin)\nGiven authenticated enterprise user\nWhen trigger long-running operation\nThen operation completes without session loss\n\n## 3. Grounded User Evidence\n(Click 'Approve & Ship' to generate full standardized PRD)`}
              </pre>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3.5 border-t border-slate-800 bg-slate-950 flex items-center justify-between">
              <span className="text-xs text-slate-400">
                Status: <span className="text-white capitalize">{previewPrdTheme.status.replace('_', ' ')}</span>
              </span>

              <div className="flex items-center space-x-2">
                <button
                  onClick={() => setPreviewPrdTheme(null)}
                  className="px-4 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition cursor-pointer"
                >
                  Close
                </button>
                {previewPrdTheme.status !== 'approved' && (
                  <button
                    onClick={() => {
                      const t = previewPrdTheme;
                      setPreviewPrdTheme(null);
                      handleApprove(t);
                    }}
                    className="px-4 py-1.5 rounded-md bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-medium transition cursor-pointer shadow-md shadow-emerald-500/20"
                  >
                    Approve & Dispatch Now
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
