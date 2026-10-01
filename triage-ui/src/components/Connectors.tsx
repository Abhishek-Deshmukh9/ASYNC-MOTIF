'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Check, FileText, GitBranch, HardDrive, Hash, LoaderCircle, RefreshCw, Trash2, X } from 'lucide-react';
import { connectionOptions, createConnection, deleteConnection, fetchConnections, syncConnection, updateConnection } from '@/utils/api';
import type { Connection, ConnectionOption, ProviderId, SyncResult } from '@/utils/types';

type Props = {
  projectId: string;
  projectName: string;
  open: boolean;               // opened from the "Connect a tool" button
  onClose: () => void;
  onSynced: () => void;        // reload the project's sources after a sync
  onMessage: (text: string, isError?: boolean) => void;
  role?: 'owner' | 'editor' | 'viewer'; // owner connects and disconnects; editors can sync; viewers only look
};

const PROVIDERS: { id: ProviderId; name: string; blurb: string; icon: React.ReactNode }[] = [
  { id: 'notion', name: 'Notion', blurb: 'Pages and databases you share with Motif', icon: <FileText size={15}/> },
  { id: 'gdrive', name: 'Google Drive', blurb: 'Docs, Sheets, PDFs in one folder you choose', icon: <HardDrive size={15}/> },
  { id: 'slack', name: 'Slack', blurb: 'Public channels you pick (never DMs)', icon: <Hash size={15}/> },
  { id: 'github', name: 'GitHub Issues', blurb: 'Issues and comments from a repository', icon: <GitBranch size={15}/> },
];

const HELP: Record<ProviderId, { steps: string[]; field: string; placeholder: string; multiline?: boolean }> = {
  notion: {
    steps: ['Open notion.so/profile/integrations and create an internal integration named Motif.', 'Copy its secret token and paste it below.', 'In Notion, open the pages to import, then ⋯ → Connections → Motif. Motif reads only what you share.'],
    field: 'Integration secret', placeholder: 'ntn_… or secret_…',
  },
  gdrive: {
    steps: ['In Google Cloud, create a project, enable the Google Drive API, then create a service account and download its JSON key.', 'Paste the whole key file below.', 'Next you will share one Drive folder with the service account email (Viewer). Motif reads only that folder.'],
    field: 'Service account key (JSON)', placeholder: '{ "type": "service_account", … }', multiline: true,
  },
  slack: {
    steps: ['At api.slack.com/apps create an app, add the bot scopes channels:read, channels:history, channels:join and users:read, then install it to your workspace.', 'Copy the Bot User OAuth Token (starts with xoxb-) and paste it below.', 'Next you will choose the public channels to read. DMs and private channels are never read.'],
    field: 'Bot token', placeholder: 'xoxb-…',
  },
  github: {
    steps: ['Enter the repository as owner/repo. Public repositories work without a token.', 'For a private repository, create a token at github.com/settings/tokens with read access to Issues (repo scope) and paste it below.', 'Motif imports issues and their comments, not pull requests.'],
    field: 'Access token (optional for public repositories)', placeholder: 'ghp_… or leave empty',
  },
};

const ago = (iso?: string | null) => {
  if (!iso) return 'never synced';
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
};
const summary = (r: SyncResult) => {
  const parts = [r.imported && `${r.imported} new`, r.updated && `${r.updated} updated`, r.removed && `${r.removed} removed`, r.unchanged && `${r.unchanged} unchanged`].filter(Boolean);
  const failed = r.failed ? ` ${r.failed} could not be read${r.errors[0] ? ` (${r.errors[0]})` : ''}.` : '';
  return `${parts.length ? parts.join(', ') : 'Nothing to import yet'}.${failed}`;
};

export default function Connectors({ projectId, projectName, open, onClose, onSynced, onMessage, role = 'owner' }: Props) {
  const isOwner = role === 'owner';
  const canSync = role !== 'viewer';
  const [connections, setConnections] = useState<Connection[]>([]);
  const [busy, setBusy] = useState('');
  const [picker, setPicker] = useState<ProviderId | null>(null);     // credential form for a provider
  const [secret, setSecret] = useState('');
  const [repo, setRepo] = useState('');
  const [formError, setFormError] = useState('');
  const [scope, setScope] = useState<Connection | null>(null);       // choose what to import
  const [options, setOptions] = useState<ConnectionOption[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [everything, setEverything] = useState(true);
  const [folderLink, setFolderLink] = useState('');
  const [optionsError, setOptionsError] = useState('');

  const load = useCallback(() => fetchConnections(projectId).then(setConnections).catch(() => setConnections([])), [projectId]);
  useEffect(() => { load(); }, [load]);

  const closeAll = () => { setPicker(null); setScope(null); setSecret(''); setFormError(''); onClose(); };

  const openScope = async (connection: Connection) => {
    setScope(connection); setPicker(null); setOptions([]); setOptionsError('');
    setChosen(connection.config.channel_ids || connection.config.page_ids || (connection.config.folder_id ? [connection.config.folder_id] : []));
    setEverything(!(connection.config.page_ids || []).length); setFolderLink('');
    try { setOptions(await connectionOptions(connection.id)); } catch (cause) { setOptionsError(cause instanceof Error ? cause.message : 'Could not load the list.'); }
  };

  const connect = async (event: FormEvent) => {
    event.preventDefault();
    if (!picker) return;
    setBusy('connect'); setFormError('');
    try {
      const credentials = picker === 'gdrive' ? { service_account: secret.trim() } : picker === 'github' ? { repo: repo.trim(), token: secret.trim() } : { token: secret.trim() };
      const created = await createConnection(projectId, projectName, picker, credentials);
      setSecret(''); setRepo(''); await load();
      if (picker === 'github') { setPicker(null); onClose(); await runSync(created); } else await openScope(created);
    } catch (cause) { setFormError(cause instanceof Error ? cause.message : 'Could not connect.'); }
    finally { setBusy(''); }
  };

  const runSync = async (connection: Connection) => {
    setBusy(connection.id);
    try {
      const result = await syncConnection(connection.id);
      onMessage(`${connection.label}: ${summary(result)}`, false);
      onSynced();
    } catch (cause) { onMessage(cause instanceof Error ? cause.message : 'Sync failed.', true); }
    finally { setBusy(''); load(); }
  };

  const saveScope = async (event: FormEvent) => {
    event.preventDefault();
    if (!scope) return;
    const config: Record<string, unknown> = {};
    if (scope.provider === 'notion') config.page_ids = everything ? [] : chosen;
    if (scope.provider === 'slack') {
      if (!chosen.length) { setOptionsError('Choose at least one channel.'); return; }
      config.channel_ids = chosen;
    }
    if (scope.provider === 'gdrive') {
      const folder = folderLink.trim() || chosen[0];
      if (!folder) { setOptionsError('Choose a folder or paste its link.'); return; }
      config.folder_id = folder;
    }
    setBusy('scope'); setOptionsError('');
    try {
      const updated = await updateConnection(scope.id, config);
      setScope(null); onClose(); await load();
      await runSync(updated);
    } catch (cause) { setOptionsError(cause instanceof Error ? cause.message : 'Could not save.'); }
    finally { setBusy(''); }
  };

  const disconnect = async (connection: Connection) => {
    const keep = window.confirm(`Disconnect ${connection.label}?\n\nOK keeps what was already imported. Cancel to stop.`);
    if (!keep) return;
    setBusy(connection.id);
    try { await deleteConnection(connection.id, false); onMessage(`${connection.label} disconnected. Imported sources were kept.`, false); }
    catch (cause) { onMessage(cause instanceof Error ? cause.message : 'Could not disconnect.', true); }
    finally { setBusy(''); load(); }
  };

  const toggle = (id: string) => setChosen((current) => current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  const showPicker = open && !picker && !scope;

  return <>
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6">
      <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-900">Connect your tools</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">read-only</span></div>
      <p className="mt-2 text-xs leading-5 text-slate-500">Pull notes, docs and conversations in automatically. Motif reads only what you choose.</p>
      <div className="mt-4 space-y-2.5">
        {PROVIDERS.map((provider) => {
          const connection = connections.find((item) => item.provider === provider.id);
          return <div key={provider.id} className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700">{provider.icon}</span>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-slate-900">{provider.name}{connection?.display_name ? <span className="ml-2 font-normal text-slate-500">{connection.display_name}</span> : null}</div>
              <div className={`truncate text-[11px] ${connection?.status === 'error' ? 'text-rose-600' : 'text-slate-500'}`}>
                {connection ? (connection.status === 'error' && connection.last_error ? connection.last_error : `${connection.sources} source${connection.sources === 1 ? '' : 's'} · ${ago(connection.last_synced_at)}`) : provider.blurb}
              </div>
            </div>
            {connection ? <div className="flex items-center gap-1">
              {canSync && <button onClick={() => runSync(connection)} disabled={busy === connection.id} title="Sync now" aria-label={`Sync ${provider.name}`} className="icon-btn !h-8 !w-8">{busy === connection.id ? <LoaderCircle size={14} className="animate-spin"/> : <RefreshCw size={14}/>}</button>}
              {isOwner && provider.id !== 'github' && <button onClick={() => openScope(connection)} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-medium text-slate-700 hover:bg-slate-50">Choose</button>}
              {isOwner && <button onClick={() => disconnect(connection)} title="Disconnect" aria-label={`Disconnect ${provider.name}`} className="icon-btn !h-8 !w-8"><Trash2 size={14}/></button>}
            </div> : !isOwner ? <span className="text-[10px] text-slate-400">Owner connects</span> : <button onClick={() => { setPicker(provider.id); setSecret(''); setRepo(''); setFormError(''); }} className="rounded-lg bg-[#0f766e] px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-[#115e59]">Connect</button>}
          </div>;
        })}
      </div>
    </div>

    {showPicker && <div className="modal-backdrop"><div className="modal-card"><div className="flex items-start justify-between"><h2 className="text-lg font-semibold text-slate-900">Connect a tool</h2><button onClick={closeAll} aria-label="Close" className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div>
      <div className="mt-4 space-y-2.5">{PROVIDERS.map((provider) => <button key={provider.id} onClick={() => { setPicker(provider.id); setSecret(''); setFormError(''); }} className="flex w-full items-center gap-3 rounded-xl border border-slate-200 px-3 py-3 text-left hover:bg-slate-50"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">{provider.icon}</span><span><span className="block text-xs font-semibold text-slate-900">{provider.name}</span><span className="block text-[11px] text-slate-500">{provider.blurb}</span></span></button>)}</div></div></div>}

    {picker && <div className="modal-backdrop"><form onSubmit={connect} className="modal-card">
      <div className="flex items-start justify-between"><h2 className="text-lg font-semibold text-slate-900">Connect {PROVIDERS.find((p) => p.id === picker)?.name}</h2><button type="button" onClick={closeAll} aria-label="Close" className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div>
      <ol className="mt-4 list-decimal space-y-1.5 pl-4 text-xs leading-5 text-slate-600">{HELP[picker].steps.map((step) => <li key={step}>{step}</li>)}</ol>
      {picker === 'github' && <label className="mt-5 block text-[11px] font-medium text-slate-600">Repository<input required value={repo} onChange={(e) => setRepo(e.target.value)} className="field mt-2 w-full" placeholder="acme/product"/></label>}
      <label className="mt-4 block text-[11px] font-medium text-slate-600">{HELP[picker].field}
        {HELP[picker].multiline
          ? <textarea required value={secret} onChange={(e) => setSecret(e.target.value)} rows={5} spellCheck={false} className="field mt-2 w-full font-mono !text-[11px]" placeholder={HELP[picker].placeholder}/>
          : <input required={picker !== 'github'} type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} className="field mt-2 w-full" placeholder={HELP[picker].placeholder}/>}
      </label>
      <p className="mt-2 text-[10px] leading-4 text-slate-400">Stored encrypted on the Motif server and never shown again. Motif only reads; it never writes to your tools.</p>
      {formError && <p role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{formError}</p>}
      <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={closeAll} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Cancel</button><button disabled={busy === 'connect'} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-4 py-2 text-xs font-semibold text-white disabled:opacity-60">{busy === 'connect' && <LoaderCircle size={13} className="animate-spin"/>}Connect</button></div>
    </form></div>}

    {scope && <div className="modal-backdrop"><form onSubmit={saveScope} className="modal-card">
      <div className="flex items-start justify-between"><div><h2 className="text-lg font-semibold text-slate-900">Choose what to import</h2><p className="mt-1 text-xs text-slate-500">{scope.label}{scope.display_name ? ` · ${scope.display_name}` : ''}</p></div><button type="button" onClick={closeAll} aria-label="Close" className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div>
      {scope.provider === 'gdrive' && <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">In Google Drive, share your folder with <b className="break-all">{scope.display_name}</b> as Viewer. It then appears in the list below.</p>}
      {scope.provider === 'notion' && <div className="mt-4 space-y-2 text-xs text-slate-700">
        <label className="flex items-center gap-2"><input type="radio" checked={everything} onChange={() => setEverything(true)}/> Everything shared with Motif</label>
        <label className="flex items-center gap-2"><input type="radio" checked={!everything} onChange={() => setEverything(false)}/> Only the pages I select</label></div>}
      {scope.provider === 'slack' && <p className="mt-4 text-xs text-slate-500">Public channels only. The last 90 days are imported.</p>}
      <div className="mt-3 max-h-56 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2">
        {!options.length && !optionsError && <div className="flex items-center gap-2 px-2 py-2 text-xs text-slate-500"><LoaderCircle size={13} className="animate-spin"/> Loading…</div>}
        {!options.length && optionsError && <p className="px-2 py-2 text-xs text-rose-700">{optionsError}</p>}
        {options.map((option) => scope.provider === 'gdrive'
          ? <label key={option.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50"><input type="radio" name="folder" checked={chosen[0] === option.id && !folderLink} onChange={() => { setChosen([option.id]); setFolderLink(''); }}/> {option.name}</label>
          : <label key={option.id} className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 ${scope.provider === 'notion' && everything ? 'opacity-40' : ''}`}><input type="checkbox" disabled={scope.provider === 'notion' && everything} checked={chosen.includes(option.id)} onChange={() => toggle(option.id)}/> {option.name}</label>)}
      </div>
      {scope.provider === 'gdrive' && <label className="mt-3 block text-[11px] font-medium text-slate-600">Or paste a folder link<input value={folderLink} onChange={(e) => setFolderLink(e.target.value)} className="field mt-2 w-full" placeholder="https://drive.google.com/drive/folders/…"/></label>}
      {options.length > 0 && optionsError && <p role="alert" className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{optionsError}</p>}
      <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={closeAll} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Later</button><button disabled={busy === 'scope'} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-4 py-2 text-xs font-semibold text-white disabled:opacity-60">{busy === 'scope' ? <LoaderCircle size={13} className="animate-spin"/> : <Check size={13}/>}Save and import</button></div>
    </form></div>}
  </>;
}
