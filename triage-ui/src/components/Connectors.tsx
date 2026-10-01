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
  { id: 'notion', name: 'Notion', blurb: 'Pages and databases you share with Motif', icon: <FileText size={16}/> },
  { id: 'gdrive', name: 'Google Drive', blurb: 'Docs, Sheets, PDFs in one folder you choose', icon: <HardDrive size={16}/> },
  { id: 'slack', name: 'Slack', blurb: 'Public channels you pick (never DMs)', icon: <Hash size={16}/> },
  { id: 'github', name: 'GitHub Issues', blurb: 'Issues and comments from a repository', icon: <GitBranch size={16}/> },
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

  const close = <button type="button" onClick={closeAll} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>;

  return <>
    <section className="panel overflow-hidden" aria-label="Connected tools">
      <div className="border-b border-rule px-5 py-4 sm:px-7">
        <h2 className="text-[15px] font-semibold text-ink">Connected tools</h2>
        <p className="text-[13px] text-muted">Motif reads only what you choose and never writes back to these tools.</p>
      </div>
      <ul>
        {PROVIDERS.map((provider, index) => {
          const connection = connections.find((item) => item.provider === provider.id);
          const failed = connection?.status === 'error' && connection.last_error;
          return <li key={provider.id} className={`flex items-center gap-3 px-5 py-3 sm:px-7 ${index ? 'border-t border-rule' : ''}`}>
            <span className="shrink-0 text-muted">{provider.icon}</span>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-ink">{provider.name}{connection?.display_name ? <span className="font-normal text-muted"> ({connection.display_name})</span> : null}</p>
              <p className={`truncate text-[13px] ${failed ? 'text-danger' : 'text-muted'}`}>
                {connection ? (failed ? connection.last_error : `${connection.sources} source${connection.sources === 1 ? '' : 's'}, synced ${ago(connection.last_synced_at)}`) : provider.blurb}
              </p>
            </div>
            {connection ? <div className="flex shrink-0 items-center gap-1">
              {canSync && <button onClick={() => runSync(connection)} disabled={busy === connection.id} aria-label={`Sync ${provider.name}`} className="btn-text">{busy === connection.id ? <LoaderCircle size={14} className="animate-spin"/> : <RefreshCw size={14}/>}<span className="hidden sm:inline">Sync</span></button>}
              {isOwner && provider.id !== 'github' && <button onClick={() => openScope(connection)} className="btn-text">Choose</button>}
              {isOwner && <button onClick={() => disconnect(connection)} title="Disconnect" aria-label={`Disconnect ${provider.name}`} className="icon-btn hover:text-danger"><Trash2 size={15}/></button>}
            </div> : !isOwner ? <span className="shrink-0 text-[13px] text-muted">The owner connects tools</span> : <button onClick={() => { setPicker(provider.id); setSecret(''); setRepo(''); setFormError(''); }} className="btn shrink-0">Connect</button>}
          </li>;
        })}
      </ul>
    </section>

    {showPicker && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Connect a tool"><div className="modal-card">
      <div className="flex items-start justify-between gap-3"><h2 className="text-[18px] font-semibold text-ink">Connect a tool</h2>{close}</div>
      <ul className="mt-3">{PROVIDERS.map((provider, index) => <li key={provider.id} className={index ? 'border-t border-rule' : ''}><button onClick={() => { setPicker(provider.id); setSecret(''); setFormError(''); }} className="flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-paper"><span className="text-muted">{provider.icon}</span><span><span className="block font-medium text-ink">{provider.name}</span><span className="block text-[13px] text-muted">{provider.blurb}</span></span></button></li>)}</ul>
    </div></div>}

    {picker && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`Connect ${PROVIDERS.find((p) => p.id === picker)?.name}`}><form onSubmit={connect} className="modal-card">
      <div className="flex items-start justify-between gap-3"><h2 className="text-[18px] font-semibold text-ink">Connect {PROVIDERS.find((p) => p.id === picker)?.name}</h2>{close}</div>
      <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-[13px] leading-relaxed text-muted">{HELP[picker].steps.map((step) => <li key={step}>{step}</li>)}</ol>
      {picker === 'github' && <label className="mt-5 block text-[13px] font-medium text-ink">Repository<input required value={repo} onChange={(e) => setRepo(e.target.value)} className="field mt-1.5 w-full" placeholder="owner/repo"/></label>}
      <label className="mt-4 block text-[13px] font-medium text-ink">{HELP[picker].field}
        {HELP[picker].multiline
          ? <textarea required value={secret} onChange={(e) => setSecret(e.target.value)} rows={5} spellCheck={false} className="field mt-1.5 w-full font-mono !text-[12px]" placeholder={HELP[picker].placeholder}/>
          : <input required={picker !== 'github'} type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} className="field mt-1.5 w-full" placeholder={HELP[picker].placeholder}/>}
      </label>
      <p className="mt-2 text-[12px] leading-snug text-muted">Stored encrypted on the Motif server and never shown again.</p>
      {formError && <p role="alert" className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-[13px] text-danger">{formError}</p>}
      <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={closeAll} className="btn-text">Cancel</button><button disabled={busy === 'connect'} className="btn-primary">{busy === 'connect' && <LoaderCircle size={14} className="animate-spin"/>}Connect</button></div>
    </form></div>}

    {scope && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Choose what to import"><form onSubmit={saveScope} className="modal-card">
      <div className="flex items-start justify-between gap-3"><div><h2 className="text-[18px] font-semibold text-ink">Choose what to import</h2><p className="mt-0.5 text-[13px] text-muted">{scope.label}{scope.display_name ? `, ${scope.display_name}` : ''}</p></div>{close}</div>
      {scope.provider === 'gdrive' && <p className="mt-4 rounded-md bg-caution-soft px-3 py-2 text-[13px] leading-relaxed text-caution">In Google Drive, share your folder with <b className="break-all">{scope.display_name}</b> as Viewer. It then appears in the list below.</p>}
      {scope.provider === 'notion' && <div className="mt-4 space-y-2 text-[14px] text-ink">
        <label className="flex items-center gap-2"><input type="radio" checked={everything} onChange={() => setEverything(true)}/> Everything shared with Motif</label>
        <label className="flex items-center gap-2"><input type="radio" checked={!everything} onChange={() => setEverything(false)}/> Only the pages I select</label></div>}
      {scope.provider === 'slack' && <p className="mt-4 text-[13px] text-muted">Public channels only. The last 90 days are imported.</p>}
      <div className="mt-3 max-h-56 space-y-0.5 overflow-y-auto rounded-md border border-rule p-1.5">
        {!options.length && !optionsError && <p className="flex items-center gap-2 px-2 py-2 text-[13px] text-muted"><LoaderCircle size={14} className="animate-spin"/> Loading</p>}
        {!options.length && optionsError && <p className="px-2 py-2 text-[13px] text-danger">{optionsError}</p>}
        {options.map((option) => scope.provider === 'gdrive'
          ? <label key={option.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-[14px] text-ink hover:bg-paper"><input type="radio" name="folder" checked={chosen[0] === option.id && !folderLink} onChange={() => { setChosen([option.id]); setFolderLink(''); }}/> {option.name}</label>
          : <label key={option.id} className={`flex items-center gap-2 rounded px-2 py-1.5 text-[14px] text-ink hover:bg-paper ${scope.provider === 'notion' && everything ? 'opacity-40' : ''}`}><input type="checkbox" disabled={scope.provider === 'notion' && everything} checked={chosen.includes(option.id)} onChange={() => toggle(option.id)}/> {option.name}</label>)}
      </div>
      {scope.provider === 'gdrive' && <label className="mt-3 block text-[13px] font-medium text-ink">Or paste a folder link<input value={folderLink} onChange={(e) => setFolderLink(e.target.value)} className="field mt-1.5 w-full" placeholder="https://drive.google.com/drive/folders/…"/></label>}
      {options.length > 0 && optionsError && <p role="alert" className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-[13px] text-danger">{optionsError}</p>}
      <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={closeAll} className="btn-text">Later</button><button disabled={busy === 'scope'} className="btn-primary">{busy === 'scope' ? <LoaderCircle size={14} className="animate-spin"/> : <Check size={14}/>}Save and import</button></div>
    </form></div>}
  </>;
}
