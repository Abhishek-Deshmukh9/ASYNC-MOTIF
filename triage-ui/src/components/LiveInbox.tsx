'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Clipboard, LoaderCircle, Send, X } from 'lucide-react';
import { createInboxWebhook, deleteInboxWebhook, fetchInbox, sendToInbox } from '@/utils/api';
import type { InboxItem, InboxMatch, InboxState } from '@/utils/types';

const POLL_MS = 4000;
const SAMPLE = 'The export stops after 10,000 rows and nothing tells us'  // used in the example command;
const pct = (value?: number) => `${Math.round((value ?? 0) * 100)}%`;

function ago(iso?: string | null) {
  if (!iso) return '';
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

const points = (value: number) => (Math.round(value * 10) / 10).toString();

// What happened to one message, in the numbers that moved
function Outcome({ entry }: { entry: InboxItem }) {
  const match: InboxMatch = entry.match;
  if (entry.duplicate) return <p className="text-[13px] text-muted">Already received. Nothing changed.</p>;
  if (match.status !== 'joined') {
    return <p className="text-[13px] leading-relaxed text-muted" data-testid="live-waiting">Waiting. {match.reason}</p>;
  }
  const moved = match.rank_before !== match.rank_after;
  const changes = (match.signals ?? []).filter((signal) => signal.points_after !== signal.points_before || signal.value_after !== signal.value_before);
  return (
    <div className="space-y-2.5 text-[13px] leading-relaxed" data-testid="live-joined">
      <p className="text-ink">
        Joined <span className="font-semibold">“{(match.theme_title ?? '').replace(/\.$/, '')}”</span>
        <span className="text-muted">. It is {pct(match.similarity)} similar to the closest message in that theme{match.threshold ? ` (a theme needs ${pct(match.threshold)})` : ''}:</span>
      </p>
      {match.closest_text && <p className="max-w-[70ch] border-l-2 border-rule pl-3 font-serif text-[14px] text-muted">“{match.closest_text.length > 150 ? `${match.closest_text.slice(0, 150)}…` : match.closest_text}”</p>}
      <p className="text-ink">
        {moved
          ? <>Rank <span className="font-semibold">{match.rank_before} → {match.rank_after}</span> of {match.of}</>
          : <>Still rank <span className="font-semibold">{match.rank_after}</span> of {match.of}</>}
        <span className="text-muted">, score {points(match.score_before ?? 0)} → {points(match.score_after ?? 0)}.</span>
        {match.type_before && match.type_after && match.type_before !== match.type_after && <span className="text-muted"> Kind of problem now reads {match.type_after}.</span>}
      </p>
      {changes.length > 0 && (
        <ul className="space-y-0.5 text-muted">
          {changes.map((change) => (
            <li key={change.key}>
              <span className="text-ink">{change.label}</span>: {change.value_before ?? 'not used before'} → {change.value_after}
              <span> ({change.points_after >= change.points_before ? '+' : ''}{points(change.points_after - change.points_before)} points)</span>
            </li>
          ))}
        </ul>
      )}
      {(match.moved?.length ?? 0) > 0 && <p className="text-muted">Also moved: {match.moved!.filter((item) => item.theme_id !== match.theme_id).map((item) => `“${item.title.replace(/^Issue:\s*/, '').slice(0, 46)}” ${item.from} → ${item.to}`).join('; ') || 'nothing else'}.</p>}
      {match.theme_status === 'approved' && <p className="text-caution">This theme is already approved{match.github_issue_url ? `; its GitHub issue is open at ${match.github_issue_url}` : ''}. The message is added to its evidence.</p>}
    </div>
  );
}

export default function LiveInbox({ projectId, onArrived }: { projectId?: string; onArrived: (entries: InboxItem[]) => void }) {
  const [state, setState] = useState<InboxState | null>(null);
  const [text, setText] = useState('');
  const [source, setSource] = useState('discord');
  const [customer, setCustomer] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [last, setLast] = useState<InboxItem | null>(null);
  const [showFeed, setShowFeed] = useState(false);
  const [showHook, setShowHook] = useState(false);
  const [link, setLink] = useState<{ url: string } | null>(null);
  const [busyLink, setBusyLink] = useState(false);
  const [copied, setCopied] = useState('');
  const top = useRef<string | null | undefined>(undefined); // newest message already seen (undefined: first read not done)
  const onArrivedRef = useRef(onArrived);
  useEffect(() => { onArrivedRef.current = onArrived; });

  // Read the feed now and every few seconds, so a message sent from another tool shows up while you watch
  useEffect(() => {
    let stopped = false;
    const read = async () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      try {
        const next = await fetchInbox(projectId);
        if (stopped) return;
        setState(next);
        const newest = next.items[0]?.id ?? null;
        if (top.current !== undefined && newest && newest !== top.current) {
          const known = top.current;
          const index = known ? next.items.findIndex((item) => item.id === known) : -1;
          const fresh = (index === -1 ? next.items : next.items.slice(0, index)).filter((item) => item.match.status === 'joined').reverse();
          if (fresh.length) onArrivedRef.current(fresh);
        }
        top.current = newest;
      } catch { /* the page shows API problems elsewhere; keep the last feed */ }
    };
    void read();
    const timer = setInterval(read, POLL_MS);
    return () => { stopped = true; clearInterval(timer); };
  }, [projectId]);

  const send = async () => {
    const message = text.trim();
    if (!message || sending) return;
    setSending(true); setError('');
    try {
      const entry = await sendToInbox(projectId, { text: message, source, customer: customer.trim() });
      setLast(entry); setText(''); setCustomer('');
      if (!entry.duplicate) top.current = entry.id;
      setState((current) => current ? { ...current, items: [entry, ...current.items.filter((item) => item.id !== entry.id)].slice(0, 20) } : current);
      if (entry.match.status === 'joined' && !entry.duplicate) onArrived([entry]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not add the message.'); }
    finally { setSending(false); }
  };

  const makeLink = async () => {
    if (!projectId) return;
    setBusyLink(true); setError('');
    try {
      const made = await createInboxWebhook(projectId);
      setLink({ url: `${window.location.origin}${made.path}` });
      setState((current) => current ? { ...current, webhook: { ...current.webhook, enabled: true, hint: made.hint } } : current);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not make the link.'); }
    finally { setBusyLink(false); }
  };

  const turnOff = async () => {
    if (!projectId) return;
    setBusyLink(true); setError('');
    try {
      await deleteInboxWebhook(projectId);
      setLink(null);
      setState((current) => current ? { ...current, webhook: { ...current.webhook, enabled: false, hint: null } } : current);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not turn the link off.'); }
    finally { setBusyLink(false); }
  };

  const copy = async (value: string, what: string) => {
    try { await navigator.clipboard.writeText(value); setCopied(what); setTimeout(() => setCopied(''), 1500); }
    catch { setError('Could not copy. Select the text and copy it instead.'); }
  };

  if (!state || (!state.can_send && state.items.length === 0)) return null;
  const waiting = state.items.filter((item) => !item.now_in).length;
  const curl = link ? `curl -X POST '${link.url}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"text": "${SAMPLE}", "from": "Maya", "source": "discord"}'` : '';

  return (
    <section className="panel mb-5 overflow-hidden" aria-label="Live feedback" data-testid="live-inbox">
      <div className="px-5 py-4 sm:px-7">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-[15px] font-semibold text-ink">Live feedback</h2>
          <p className="text-[13px] text-muted">A new message joins the closest theme and the ranking updates. No re-analysis needed.</p>
        </div>

        {state.can_send ? (
          <div className="mt-3">
            <label className="sr-only" htmlFor="live-text">Customer message</label>
            <textarea
              id="live-text" data-testid="live-text" value={text} onChange={(event) => setText(event.target.value)} rows={2} maxLength={8000}
              onKeyDown={(event) => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void send(); } }}
              placeholder="Paste what a customer wrote" className="field w-full resize-y"
            />
            <div className="mt-2 grid gap-2 sm:grid-cols-[11rem_minmax(0,1fr)_auto] xl:grid-cols-2">
              <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Where it came from" className="field min-w-0">
                {Object.entries(state.sources).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              <input value={customer} onChange={(event) => setCustomer(event.target.value)} aria-label="Customer (optional)" placeholder="Customer (optional)" className="field min-w-0" maxLength={200}/>
              <button onClick={() => void send()} disabled={sending || !text.trim() || state.analysis_running} data-testid="live-send" title={state.analysis_running ? 'An analysis is running. Try again in a moment.' : 'Ctrl or Cmd + Enter'} className="btn-primary xl:col-span-2">
                {sending ? <LoaderCircle size={14} className="animate-spin"/> : <Send size={14}/>} Add message
              </button>
            </div>
            <p className="mt-1.5 text-[12px] text-muted">Revenue only counts if the customer is already in this project&apos;s data. Motif doesn&apos;t guess an account&apos;s value.</p>
          </div>
        ) : (
          <p className="mt-2 text-[13px] text-muted">You have view-only access. Messages sent to this project appear here as they arrive.</p>
        )}

        {error && <p role="alert" className="mt-3 rounded-md border-l-[3px] border-danger bg-danger-soft px-3 py-2 text-[13px] text-danger">{error}</p>}
        {last && (
          <div className="mt-4 rounded-md bg-paper px-4 py-3" data-testid="live-result" aria-live="polite">
            <div className="mb-1.5 flex items-start justify-between gap-3">
              <p className="line-clamp-2 max-w-[70ch] font-serif text-[15px] text-ink">“{last.text}”</p>
              <button onClick={() => setLast(null)} aria-label="Dismiss" className="icon-btn -my-1 -mr-2 h-7 w-7 shrink-0"><X size={14}/></button>
            </div>
            <Outcome entry={last}/>
          </div>
        )}
      </div>

      <div className="border-t border-rule">
        <button onClick={() => setShowFeed((value) => !value)} aria-expanded={showFeed} className="flex w-full items-center justify-between gap-3 px-5 py-2.5 text-left text-[13px] font-medium text-ink hover:bg-paper sm:px-7">
          <span>Recent messages <span className="font-normal text-muted">{state.items.length}{waiting ? `, ${waiting} waiting for the next Analyze` : ''}</span></span>
          <ChevronDown size={15} className={`text-muted transition-transform ${showFeed ? 'rotate-180' : ''}`}/>
        </button>
        {showFeed && (state.items.length ? (
          <ul className="border-t border-rule" data-testid="live-feed">
            {state.items.map((item, index) => (
              <li key={item.id} className={`px-5 py-3 text-[13px] sm:px-7 ${index ? 'border-t border-rule' : ''}`}>
                <p className="line-clamp-2 max-w-[75ch] text-ink">{item.text}</p>
                <p className="mt-0.5 text-muted">
                  {[item.source, item.author, item.customer, ago(item.received_at)].filter(Boolean).join(', ')}
                  {item.via === 'webhook' ? ', via webhook' : ''}
                  {' · '}
                  {item.now_in ? <span className="text-ink">in “{item.now_in.title.replace(/^Issue:\s*/, '').slice(0, 60)}”</span> : 'waiting for the next Analyze'}
                </p>
              </li>
            ))}
          </ul>
        ) : <p className="border-t border-rule px-5 py-3 text-[13px] text-muted sm:px-7">Nothing yet.</p>)}
      </div>

      {state.webhook.available && (state.can_manage_webhook || state.webhook.enabled) && (
        <div className="border-t border-rule">
          <button onClick={() => setShowHook((value) => !value)} aria-expanded={showHook} className="flex w-full items-center justify-between gap-3 px-5 py-2.5 text-left text-[13px] font-medium text-ink hover:bg-paper sm:px-7">
            <span>Send from other tools <span className="font-normal text-muted">{state.webhook.enabled ? `link on, ends …${state.webhook.hint}` : 'Discord, support desk, Zapier or curl'}</span></span>
            <ChevronDown size={15} className={`text-muted transition-transform ${showHook ? 'rotate-180' : ''}`}/>
          </button>
          {showHook && (
            <div className="space-y-3 border-t border-rule px-5 py-4 text-[13px] leading-relaxed sm:px-7" data-testid="live-webhook">
              <p className="max-w-[72ch] text-muted">Anything that can send an HTTP request can post a message here: a Discord bot, your support desk&apos;s webhook, Zapier, or a command. The link is secret, so anyone who has it can add messages. Motif keeps only a fingerprint of it.</p>
              {link ? (
                <>
                  <p className="font-medium text-ink">Copy it now. For safety it is shown once.</p>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-md bg-paper px-3 py-2 text-[12px] text-ink" data-testid="live-link">{link.url}</code>
                    <button onClick={() => void copy(link.url, 'link')} className="btn shrink-0">{copied === 'link' ? <Check size={14}/> : <Clipboard size={14}/>} Copy</button>
                  </div>
                  <div>
                    <p className="mb-1 text-muted">Try it from a terminal:</p>
                    <pre className="overflow-x-auto rounded-md bg-paper px-3 py-2 text-[12px] leading-relaxed text-ink">{curl}</pre>
                    <button onClick={() => void copy(curl, 'curl')} className="btn-text mt-1">{copied === 'curl' ? <Check size={14}/> : <Clipboard size={14}/>} Copy command</button>
                  </div>
                  <p className="text-muted">Outside tools need an address on the internet. While testing on your laptop, a tunnel such as ngrok gives you one.</p>
                </>
              ) : state.webhook.enabled ? (
                <p className="text-muted">A link is on. For safety it can&apos;t be shown again. {state.can_manage_webhook ? 'Make a new one to replace it, or turn it off.' : 'The project owner can replace it.'}</p>
              ) : null}
              {state.can_manage_webhook && (
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => void makeLink()} disabled={busyLink} className="btn">{busyLink && <LoaderCircle size={14} className="animate-spin"/>}{state.webhook.enabled ? 'Replace the link' : 'Make a link'}</button>
                  {state.webhook.enabled && <button onClick={() => void turnOff()} disabled={busyLink} className="btn-danger">Turn it off</button>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
