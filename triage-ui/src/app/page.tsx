'use client';

import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowDown, ArrowRight, AudioLines, Award, Check, CheckCircle2,
  CircleHelp, Clipboard, Cloud, DollarSign, ExternalLink, FileText, FlaskConical, FolderKanban, FolderOpen, GitBranch, HardDrive, Headphones,
  LoaderCircle, Mic, MicOff, Plus, Radio, RefreshCw, Search, ShieldCheck, Sparkles, Timer, Trash2,
  Upload, X, Zap,
} from 'lucide-react';
import { approveTheme, deleteSource, fetchMetrics, fetchPipelineStatus, fetchSources, fetchThemes, ingestSource, rejectTheme, runPipeline, uploadSources } from '@/utils/api';
import type { EvalMetrics, Project, ProjectSource, Theme, UploadFileResult, UploadedSource } from '@/utils/types';

const STORE_KEY = 'motif-project-workspaces-v1';
type SpeechResultEvent = { resultIndex: number; results: ArrayLike<{ isFinal: boolean; [index: number]: { transcript: string } }> };
type BrowserRecognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void; stop: () => void;
};
type SpeechConstructor = new () => BrowserRecognition;
const API_HINT = 'API is not connected. Start the Motif backend to sync sources and generate themes.';
// Built-in workspace for the labelled 300-item demo corpus loaded by seed.py (feedback with no project).
const DEMO_ID = '__demo_benchmark__';
const pct = (value: number | null | undefined) => (value === null || value === undefined ? '—' : `${value}%`);
const meets = (value: number | null | undefined, target: number) => value !== null && value !== undefined && value >= target;

// File types the backend can read (see app/core/extraction.py)
const UPLOAD_TYPES = ['.pdf', '.docx', '.pptx', '.xlsx', '.md', '.markdown', '.txt', '.csv', '.json', '.html', '.htm', '.zip'];
const UPLOAD_ACCEPT = UPLOAD_TYPES.join(',');
const MAX_BATCH_FILES = 20;
const MAX_BATCH_BYTES = 8 * 1024 * 1024;
const MAX_FILE_BYTES = 25 * 1024 * 1024; // same limit as the backend
const extOf = (name: string) => { const dot = name.lastIndexOf('.'); return dot >= 0 ? name.slice(dot).toLowerCase() : ''; };
const relativePath = (file: File) => (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;
const fromServer = (source: UploadedSource): ProjectSource => ({
  id: source.id, serverId: source.id, name: source.path?.split('/').pop() || source.title, kind: 'document',
  createdAt: source.created_at || new Date().toISOString(), content: '', syncState: 'synced', passages: source.passages,
});

// One line for the notice banner: what was imported, what was already there, what could not be read
function describeUpload(results: UploadFileResult[], ignored: number, oversized: string[] = []) {
  const imported = results.flatMap((result) => result.sources);
  const passages = imported.reduce((total, source) => total + source.passages, 0);
  const duplicates = results.filter((result) => result.status === 'duplicate').length;
  const problems = [
    ...oversized.map((name) => `${name} (larger than 25 MB)`),
    ...results.filter((result) => result.status === 'failed' || result.status === 'skipped').map((result) => `${result.filename} (${result.detail || 'not imported'})`),
    ...results.flatMap((result) => result.status === 'imported' ? result.skipped.map((entry) => `${entry.path} (${entry.reason})`) : []),
  ];
  const parts = [];
  if (imported.length) parts.push(`Imported ${plural(imported.length, 'source')} (${plural(passages, 'passage')}).`);
  if (duplicates) parts.push(`${plural(duplicates, 'file')} already in this project.`);
  if (ignored) parts.push(`${plural(ignored, 'file')} ignored (hidden or unsupported).`);
  if (problems.length) parts.push(`Not imported: ${problems.slice(0, 3).join('; ')}${problems.length > 3 ? ` and ${problems.length - 3} more` : ''}.`);
  return { text: parts.join(' ') || 'Nothing new to import.', ok: imported.length > 0 || (duplicates > 0 && !problems.length) };
}

function makeId() { return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`; }
function readProjects(): Project[] {
  try { const value = localStorage.getItem(STORE_KEY); return value ? JSON.parse(value) as Project[] : []; } catch { return []; }
}

export default function Workspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState('');
  const [ready, setReady] = useState(false);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [apiOnline, setApiOnline] = useState(false);
  const [newName, setNewName] = useState('');
  const [newRepo, setNewRepo] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [showDrive, setShowDrive] = useState(false);
  const [folderUrl, setFolderUrl] = useState('');
  const [sourceSearch, setSourceSearch] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [working, setWorking] = useState('');
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [meetingName, setMeetingName] = useState('Customer discovery call');
  const [reviewTheme, setReviewTheme] = useState<Theme | null>(null);
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editSummary, setEditSummary] = useState('');
  const [prdTheme, setPrdTheme] = useState<Theme | null>(null);
  const [lastRunSeconds, setLastRunSeconds] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<BrowserRecognition | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunks = useRef<Blob[]>([]);
  const transcriptRef = useRef('');

  const isDemo = activeId === DEMO_ID;
  const activeProject = projects.find((project) => project.id === activeId) || projects[0];
  const sources = activeProject?.sources || [];
  const filteredSources = sources.filter((source) => source.name.toLowerCase().includes(sourceSearch.toLowerCase()));
  const pendingThemes = useMemo(() => themes.filter((theme) => theme.status === 'pending_review'), [themes]);
  const approvedThemes = useMemo(() => themes.filter((theme) => theme.status === 'approved'), [themes]);
  const rejectedCount = themes.filter((theme) => theme.status === 'rejected').length;

  useEffect(() => {
    // Browser storage is intentionally read after hydration to avoid SSR/client mismatch.
    const loaded = readProjects();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProjects(loaded);
    setActiveId(loaded[0]?.id || DEMO_ID);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!activeId) return;
    const demo = activeId === DEMO_ID;
    fetchThemes(demo ? undefined : activeId).then((value) => { setThemes(value); setApiOnline(true); }).catch(() => setApiOnline(false));
    if (!demo) {
      // Sources uploaded from another browser (or before this one's storage was cleared)
      fetchSources(activeId).then((server) => setProjects((current) => current.map((project) => {
        if (project.id !== activeId) return project;
        const known = new Set(project.sources.map((source) => source.serverId).filter(Boolean));
        const missing = server.filter((source) => !known.has(source.id)).map(fromServer);
        return missing.length ? { ...project, sources: [...project.sources, ...missing] } : project;
      }))).catch(() => undefined);
    }
    if (demo) {
      fetchMetrics().then(setMetrics).catch(() => setMetrics(null));
      fetchPipelineStatus().then((status) => {
        const last = status.last_result;
        if (last && !last.project_id && typeof last.duration_seconds === 'number') setLastRunSeconds(last.duration_seconds);
      }).catch(() => undefined);
    }
  }, [activeId]);

  const refresh = () => {
    fetchThemes(isDemo ? undefined : activeProject?.id).then((value) => { setThemes(value); setApiOnline(true); }).catch(() => setApiOnline(false));
    if (isDemo) fetchMetrics().then(setMetrics).catch(() => setMetrics(null));
  };

  useEffect(() => {
    if (ready) localStorage.setItem(STORE_KEY, JSON.stringify(projects));
  }, [projects, ready]);

  useEffect(() => () => {
    recognitionRef.current?.stop?.();
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  const updateProject = (id: string, updater: (project: Project) => Project) => {
    setProjects((current) => current.map((project) => project.id === id ? updater(project) : project));
  };

  const createProject = (event: React.FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    const project = { id: makeId(), name, repo: newRepo.trim(), sources: [] };
    setProjects((existing) => [...existing, project]);
    setActiveId(project.id);
    setNewName(''); setNewRepo(''); setShowCreate(false);
    setNotice(`Project “${name}” is ready. Add notes, call transcripts, or a Drive folder to get started.`);
    setError('');
  };

  const saveSource = async (source: ProjectSource, sync = true) => {
    if (!activeProject) return;
    updateProject(activeProject.id, (project) => ({ ...project, sources: [source, ...project.sources] }));
    setNotice(`Saved “${source.name}” to ${activeProject.name}.`);
    setError('');
    if (sync && apiOnline) {
      try {
        const serverId = await ingestSource(source, activeProject.id, activeProject.name);
        updateProject(activeProject.id, (project) => ({ ...project, sources: project.sources.map((item) => item.id === source.id ? { ...item, syncState: 'synced', serverId: serverId ?? undefined } : item) }));
        setNotice(`Saved “${source.name}” to ${activeProject.name} and synced it to Motif.`);
      } catch { setError('Saved in this browser, but could not sync to the backend. Check that the API and database are running.'); }
    }
  };

  // Files and folders (e.g. an Obsidian vault) are read on the backend: PDF, Word, PowerPoint,
  // Excel, Markdown, text, CSV/JSON exports and .zip archives, split into passages for analysis.
  const importFiles = async (picked: File[]) => {
    if (!activeProject || !picked.length) return;
    const project = activeProject;
    const supported = picked.filter((file) => !relativePath(file).split('/').some((part) => part.startsWith('.')) && UPLOAD_TYPES.includes(extOf(file.name)));
    const ignored = picked.length - supported.length;
    const oversized = supported.filter((file) => file.size > MAX_FILE_BYTES).map((file) => file.name);
    const usable = supported.filter((file) => file.size <= MAX_FILE_BYTES);
    if (!usable.length) {
      setNotice('');
      setError(oversized.length ? `Too large to import (25 MB limit): ${oversized.join(', ')}.` : 'None of these files can be imported. Use PDF, Word, PowerPoint, Excel, Markdown, text, CSV, JSON, HTML or .zip.');
      return;
    }
    const batches: File[][] = [];
    let batch: File[] = []; let bytes = 0;
    for (const file of usable) {
      if (batch.length && (batch.length >= MAX_BATCH_FILES || bytes + file.size > MAX_BATCH_BYTES)) { batches.push(batch); batch = []; bytes = 0; }
      batch.push(file); bytes += file.size;
    }
    if (batch.length) batches.push(batch);

    setWorking('upload'); setError(''); setNotice(`Reading ${plural(usable.length, 'file')}…`);
    const results: UploadFileResult[] = [];
    try {
      for (const [index, files] of batches.entries()) {
        if (batches.length > 1) setNotice(`Reading files… batch ${index + 1} of ${batches.length}`);
        const result = await uploadSources(files.map((file) => ({ file, name: relativePath(file) })), project.id, project.name);
        results.push(...result.files);
        const created = result.files.flatMap((item) => item.sources.map(fromServer));
        if (created.length) updateProject(project.id, (current) => ({ ...current, sources: [...created, ...current.sources] }));
      }
      setApiOnline(true);
      const summary = describeUpload(results, ignored, oversized);
      if (summary.ok) { setNotice(summary.text); setError(''); } else { setNotice(''); setError(summary.text); }
    } catch (cause) {
      setNotice('');
      setError(cause instanceof Error && cause.message !== 'Failed to fetch' ? `Upload failed: ${cause.message}` : API_HINT);
    } finally { setWorking(''); }
  };

  const onFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    await importFiles(files);
  };

  const removeSource = async (source: ProjectSource) => {
    if (!activeProject) return;
    const project = activeProject;
    setWorking(`source:${source.id}`); setError('');
    try {
      if (source.serverId) await deleteSource(source.serverId, project.id);
      updateProject(project.id, (current) => ({ ...current, sources: current.sources.filter((item) => item.id !== source.id) }));
      setNotice(`Removed “${source.name}”. Analyze again to update the themes.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not remove this source.'); }
    finally { setWorking(''); }
  };

  const startMeeting = async () => {
    if (!activeProject) return;
    setError(''); setNotice(''); setTranscript(''); transcriptRef.current = ''; audioChunks.current = [];
    const speechWindow = window as Window & { SpeechRecognition?: SpeechConstructor; webkitSpeechRecognition?: SpeechConstructor };
    const SpeechRecognitionApi = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!SpeechRecognitionApi) {
      setError('Live transcription is not supported by this browser. Try Chrome or Edge, or upload an existing transcript.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) audioChunks.current.push(event.data); };
      recorder.start();
      const recognition = new SpeechRecognitionApi();
      recognition.continuous = true; recognition.interimResults = true; recognition.lang = navigator.language || 'en-US';
      recognition.onresult = (event: SpeechResultEvent) => {
        let finalText = '';
        let interim = '';
        for (let index = 0; index < event.results.length; index++) {
          const chunk = event.results[index][0]?.transcript || '';
          if (event.results[index].isFinal) finalText += `${chunk} `; else interim += chunk;
        }
        transcriptRef.current = finalText;
        setTranscript(`${finalText}${interim}`.trim());
      };
      recognition.onerror = (event: { error: string }) => { if (event.error !== 'no-speech') setError(`Transcription issue: ${event.error}. You can stop and save anything captured so far.`); };
      recognition.onend = () => setTranscribing(false);
      recognitionRef.current = recognition;
      recognition.start(); setRecording(true); setTranscribing(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Microphone access is unavailable. Allow microphone access and try again.');
    }
  };

  const stopMeeting = async () => {
    setRecording(false); setTranscribing(false);
    recognitionRef.current?.stop?.();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      await new Promise<void>((resolve) => { recorder.onstop = () => resolve(); recorder.stop(); });
      recorder.stream.getTracks().forEach((track) => track.stop());
      if (audioChunks.current.length) {
        const audio = new Blob(audioChunks.current, { type: recorder.mimeType || 'audio/webm' });
        const audioUrl = URL.createObjectURL(audio);
        const audioLink = document.createElement('a'); audioLink.href = audioUrl; audioLink.download = `${meetingName.trim() || 'Meeting'} — audio.webm`; audioLink.click(); URL.revokeObjectURL(audioUrl);
      }
    }
    const text = transcriptRef.current.trim();
    if (!text) { setError('No speech was captured. Check the microphone and try again.'); return; }
    const filename = `${meetingName.trim() || 'Meeting transcript'} — ${new Date().toLocaleDateString()}.md`;
    const content = `# ${meetingName.trim() || 'Meeting transcript'}\n\nRecorded ${new Date().toLocaleString()}\n\n## Transcript\n\n${text}\n`;
    const source: ProjectSource = { id: makeId(), name: filename, kind: 'meeting', createdAt: new Date().toISOString(), content, syncState: 'local' };
    await saveSource(source);
    const blob = new Blob([content], { type: 'text/markdown' });
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename; link.click(); URL.revokeObjectURL(link.href);
    setTranscript(''); transcriptRef.current = '';
  };

  const runAnalysis = async () => {
    if (!sources.length) { setError('Add at least one source before analyzing this project.'); return; }
    setWorking('pipeline'); setError(''); setNotice('');
    try {
      for (const source of sources.filter((item) => item.syncState !== 'synced')) {
        const serverId = await ingestSource(source, activeProject.id, activeProject.name);
        updateProject(activeProject.id, (project) => ({ ...project, sources: project.sources.map((item) => item.id === source.id ? { ...item, syncState: 'synced', serverId: serverId ?? undefined } : item) }));
      }
      const result = await runPipeline(activeProject.id);
      const updated = await fetchThemes(activeProject.id); setThemes(updated); setApiOnline(true);
      const created = result.themes_created ?? updated.length;
      const took = typeof result.duration_seconds === 'number' ? ` in ${result.duration_seconds}s` : '';
      setNotice(created
        ? `Analysis complete${took}. ${plural(created, 'theme')} ready for your review.`
        : `Analysis complete${took}, but no themes yet. A theme needs at least 4 passages about the same problem, so add more sources and analyze again.`);
    } catch (cause) { setApiOnline(false); setError(cause instanceof Error ? cause.message : API_HINT); }
    finally { setWorking(''); }
  };

  const runDemoAnalysis = async () => {
    setWorking('pipeline'); setError(''); setNotice('');
    try {
      const result = await runPipeline();
      const [updated, latest] = await Promise.all([fetchThemes(), fetchMetrics()]);
      setThemes(updated); setMetrics(latest); setApiOnline(true);
      if (typeof result.duration_seconds === 'number') setLastRunSeconds(result.duration_seconds);
      setNotice(`Analysis complete${typeof result.duration_seconds === 'number' ? ` in ${result.duration_seconds}s` : ''}. ${result.themes_created ?? updated.length} themes discovered from the demo corpus.`);
    } catch (cause) { setApiOnline(false); setError(cause instanceof Error ? cause.message : API_HINT); }
    finally { setWorking(''); }
  };

  const openReview = (theme: Theme) => {
    setReviewTheme(theme); setEditTitle(theme.title); setEditSummary(theme.summary);
  };

  // Approve (optionally with the PM's edits), generate the PRD, dispatch to GitHub when configured
  const launchTheme = async (theme: Theme, edits?: { title: string; summary: string }) => {
    const title = edits?.title.trim() || theme.title;
    const summary = edits?.summary.trim() || theme.summary;
    setWorking(theme.id); setError('');
    try {
      const result = await approveTheme(theme.id, title, isDemo ? undefined : activeProject?.repo, summary !== theme.summary ? summary : undefined);
      const approved: Theme = { ...theme, title, summary, status: 'approved', github_issue_url: result.github_issue_url, github_issue_number: result.github_issue_number, prd_markdown: result.prd_markdown };
      setThemes((existing) => existing.map((item) => item.id === theme.id ? approved : item));
      setReviewTheme(null);
      setPrdTheme(approved);
      setNotice(result.github_issue_url ? `Issue #${result.github_issue_number} created in GitHub.` : `Theme approved and PRD generated. ${result.github_message ?? 'No GitHub issue was created.'}`);
      if (isDemo) fetchMetrics().then(setMetrics).catch(() => undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not create GitHub issue. Check the GitHub configuration.'); }
    finally { setWorking(''); }
  };

  const dismissTheme = async (theme: Theme) => {
    setWorking(theme.id); setError('');
    try {
      await rejectTheme(theme.id);
      setThemes((existing) => existing.map((item) => item.id === theme.id ? { ...item, status: 'rejected' } : item));
      setReviewTheme(null);
      setNotice(`Rejected “${theme.title}”. It stays in the audit log and counts toward the acceptance rate.`);
      if (isDemo) fetchMetrics().then(setMetrics).catch(() => undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not reject this theme.'); }
    finally { setWorking(''); }
  };

  const copyPrd = async (markdown: string) => {
    try { await navigator.clipboard.writeText(markdown); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { setError('Could not copy to the clipboard. Select the text and copy it instead.'); }
  };

  const saveDriveScope = (event: React.FormEvent) => {
    event.preventDefault();
    if (activeProject) updateProject(activeProject.id, (project) => ({ ...project, driveFolder: folderUrl.trim() }));
    setShowDrive(false);
    setNotice('Drive folder scope recorded in this browser. To securely sync it, configure Google OAuth on the Motif backend; no Drive files are read until that connector is enabled.');
  };

  const downloadSource = (source: ProjectSource) => {
    const blob = new Blob([source.content], { type: 'text/markdown' }); const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = source.name; link.click(); URL.revokeObjectURL(url);
  };


  const noticeBanner = (
    (notice || error) ? <div className={`mb-5 flex items-start justify-between gap-3 rounded-lg border px-3.5 py-3 text-xs leading-5 ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-900'}`}><div className="flex gap-2.5">{error ? <CircleHelp size={15} className="mt-0.5 shrink-0 text-rose-600"/> : <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-[#0f766e]"/>}{error || notice}</div><button onClick={() => { setNotice(''); setError(''); }} className="text-slate-500 hover:text-slate-900"><X size={14}/></button></div> : null
  );

  const roadmapSection = (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_2px_8px_rgba(15,23,42,0.035)]">
      <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 sm:px-6"><div><h2 className="text-sm font-semibold text-slate-900">Review the roadmap</h2><p className="mt-1 text-[11px] text-slate-500">Approve an evidence-backed theme to create its issue.</p></div><span className="rounded-full bg-slate-100 px-2 py-1 font-mono text-[10px] text-slate-600">{pendingThemes.length} to review</span></div>
      {pendingThemes.length ? <div className="divide-y divide-slate-100">{pendingThemes.map((theme) => <div key={theme.id} className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:px-6"><div className="flex min-w-0 flex-1 gap-3"><div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 font-mono text-xs text-amber-700">{(theme.cited_quotes || []).length}</div><div className="min-w-0"><h3 className="text-xs font-semibold text-slate-900">{theme.title}</h3><p className="mt-1 line-clamp-2 max-w-2xl text-[11px] leading-5 text-slate-500">{theme.summary}</p><div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">{theme.revenue_at_risk > 0 && <><span>{plural(theme.affected_accounts_count, 'account')}</span><span>·</span><span>${theme.revenue_at_risk.toLocaleString()} at risk</span><span>·</span></>}{theme.mention_count ? <><span>{plural(theme.mention_count, 'mention')}</span><span>·</span></> : null}<span>{theme.source_count ? `${plural(theme.source_count, 'source')}` : `${(theme.cited_quotes || []).length} cited quotes`}</span></div></div></div><div className="flex shrink-0 gap-2"><button onClick={() => dismissTheme(theme)} disabled={Boolean(working)} className="rounded-lg border border-rose-200 px-3 py-2 text-[11px] text-rose-700 hover:bg-rose-50 disabled:opacity-50">Reject</button><button onClick={() => openReview(theme)} className="rounded-lg border border-slate-200 px-3 py-2 text-[11px] text-slate-700 hover:bg-slate-100">Review &amp; edit</button><button onClick={() => launchTheme(theme)} disabled={Boolean(working)} className="flex items-center gap-1.5 rounded-lg bg-[#0f766e] px-3 py-2 text-[11px] font-semibold text-white hover:bg-[#115e59] disabled:opacity-50">{working === theme.id ? <LoaderCircle size={13} className="animate-spin"/> : <Check size={13}/>} Launch issue</button></div></div>)}</div> : <div className="px-6 py-9 text-center"><p className="text-xs font-medium text-slate-700">{themes.length ? 'Nothing waiting for approval' : 'Your themes will appear here'}</p><p className="mt-1 text-[11px] text-slate-400">{themes.length ? 'New themes are ready after another analysis.' : 'Add sources, then analyze to discover what customers are telling you.'}</p></div>}
      {(approvedThemes.length > 0 || rejectedCount > 0) && <div className="border-t border-slate-200 bg-slate-50/60 px-5 py-4 sm:px-6"><div className="mb-2 flex items-center justify-between"><h3 className="text-[11px] font-semibold uppercase tracking-[.16em] text-slate-500">Approved</h3>{rejectedCount > 0 && <span className="text-[10px] text-slate-400">{rejectedCount} rejected</span>}</div>{approvedThemes.length ? <div className="space-y-2">{approvedThemes.map((theme) => <div key={theme.id} className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="truncate text-xs font-medium text-slate-800">{theme.title}</div><div className="mt-0.5 text-[10px] text-slate-500">{theme.github_issue_url ? <a href={theme.github_issue_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[#0f766e] hover:underline">Issue #{theme.github_issue_number} <ExternalLink size={10}/></a> : 'PRD generated · not sent to GitHub'}</div></div><button onClick={() => setPrdTheme(theme)} className="self-start rounded-lg border border-slate-200 px-3 py-1.5 text-[11px] text-slate-700 hover:bg-slate-100 sm:self-auto">View PRD</button></div>)}</div> : <p className="text-[11px] text-slate-400">No approved themes yet.</p>}</div>}
    </section>
  );

  const metricCards = [
    { label: 'Theme precision P@3', icon: <Award size={14} className="text-[#0f766e]"/>, value: pct(metrics?.precision_at_3), target: 'Target ≥ 90%', met: meets(metrics?.precision_at_3, 90), sub: metrics?.precision_at_3 == null ? 'Analyze the demo feedback to measure it' : 'Top 3 themes vs. the ground-truth top 3' },
    { label: 'Accepted as-is', icon: <CheckCircle2 size={14} className="text-[#0f766e]"/>, value: pct(metrics?.acceptance_rate), target: 'Target ≥ 70%', met: meets(metrics?.acceptance_rate, 70), sub: metrics?.acceptance_rate == null ? 'No PM decisions yet' : `Approved without edits, across ${metrics.pm_decisions_count} decisions` },
    { label: 'Citation validity', icon: <ShieldCheck size={14} className="text-[#0f766e]"/>, value: pct(metrics?.citation_validity), target: 'Target 100%', met: meets(metrics?.citation_validity, 100), sub: metrics?.citation_validity == null ? 'No quotes stored yet' : `${metrics.verified_quotes_count} of ${metrics.total_quotes_count} quotes re-verified word for word` },
    { label: 'Pipeline time', icon: <Timer size={14} className="text-[#0f766e]"/>, value: lastRunSeconds === null ? '—' : `${lastRunSeconds}s`, target: 'Target < 90s', met: lastRunSeconds !== null && lastRunSeconds < 90, sub: lastRunSeconds === null ? 'Shown after the next analysis run' : 'Last demo run, embedding to ranked themes' },
    { label: 'ARR at risk', icon: <DollarSign size={14} className="text-[#0f766e]"/>, value: metrics ? `$${Math.round(metrics.total_revenue_at_risk / 1000).toLocaleString()}k` : '—', target: '', met: false, sub: `Each account counted once · ${metrics?.total_themes_discovered ?? 0} themes` },
  ];

  const demoView = <>
    <div className="mb-8 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
      <div><div className="mb-3 flex items-center gap-2 text-[11px] text-slate-500"><span>Workspaces</span><span>/</span><span className="text-slate-700">Demo benchmark</span></div><h1 className="text-[28px] font-semibold tracking-[-.045em] text-slate-900 sm:text-[34px]">Demo benchmark<span className="ml-3 align-middle text-sm font-normal tracking-normal text-slate-400">300 labelled items</span></h1><p className="mt-2 max-w-xl text-[13px] leading-5 text-slate-600">Synthetic app reviews, support emails and a sales call, loaded by <code className="font-mono text-[12px]">seed.py</code>. Every item carries a ground-truth theme label, so the metrics below are measured, not estimated.</p></div>
      <div className="flex flex-wrap items-center gap-2"><button onClick={runDemoAnalysis} disabled={working === 'pipeline'} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3.5 py-2.5 text-xs font-semibold text-white transition hover:bg-[#115e59] disabled:cursor-not-allowed disabled:opacity-40">{working === 'pipeline' ? <LoaderCircle size={14} className="animate-spin"/> : <Sparkles size={14}/>} Analyze demo feedback</button></div>
    </div>
    {noticeBanner}
    {!apiOnline && <div className="mb-5 rounded-lg border border-slate-200 bg-white px-3.5 py-3 text-xs leading-5 text-slate-600">{API_HINT}</div>}
    {apiOnline && metrics && metrics.total_feedback_items === 0 && <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3 text-xs leading-5 text-amber-900">No demo data yet. Load it with <code className="font-mono">python seed.py</code> (or <code className="font-mono">docker compose exec backend python seed.py</code>), then click Analyze demo feedback.</div>}
    <section className="mb-7 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">{metricCards.map((card) => <div key={card.label} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_2px_8px_rgba(15,23,42,0.035)]"><div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500"><span>{card.label}</span>{card.icon}</div><div className="mt-3 flex items-baseline gap-2"><span className="text-2xl font-semibold tracking-tight text-slate-900">{card.value}</span>{card.target && <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${card.met ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{card.target}</span>}</div><p className="mt-1.5 text-[11px] leading-4 text-slate-500">{card.sub}</p></div>)}</section>
    {metrics && metrics.top_3_breakdown.length > 0 && <section className="mb-7 rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6"><h2 className="text-sm font-semibold text-slate-900">How P@3 was scored</h2><p className="mt-1 text-[11px] text-slate-500">Ground-truth top 3 by revenue at risk: {metrics.ground_truth_top_3.map((label) => label.replaceAll('_', ' ')).join(' · ')}</p><div className="mt-4 divide-y divide-slate-100">{metrics.top_3_breakdown.map((row, index) => <div key={index} className="flex items-center gap-3 py-2.5 text-xs"><span className="font-mono text-[10px] text-slate-400">#{index + 1}</span><span className="min-w-0 flex-1 truncate text-slate-800">{row.title}</span><span className="hidden text-[11px] text-slate-500 sm:inline">{row.matched_ground_truth_theme ? `${row.matched_ground_truth_theme.replaceAll('_', ' ')} · ${row.purity}% pure` : 'no label'}</span>{row.is_in_ground_truth_top_3 ? <Check size={14} className="text-emerald-600"/> : <span className="text-[11px] text-amber-700">miss</span>}</div>)}</div></section>}
    {roadmapSection}
  </>;

  return <div className="min-h-screen bg-[#f4f6f8] text-slate-900">
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur-xl">
      <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between px-5 md:px-9">
        <div className="flex items-center gap-3.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#0f766e] to-[#2ca58d] text-base font-black text-white shadow-md shadow-emerald-900/15">m</div>
          <div><div className="text-[15px] font-semibold tracking-tight">motif<span className="ml-2 text-[10px] font-medium uppercase tracking-[.2em] text-slate-500">feedback intelligence</span></div></div>
          <span className="mx-2 hidden h-6 w-px bg-slate-200 sm:block" />
          <span className="hidden items-center gap-2 text-xs text-slate-600 sm:flex"><span className={`h-1.5 w-1.5 rounded-full ${apiOnline ? 'bg-emerald-500' : 'bg-slate-300'}`} />{apiOnline ? 'API connected' : 'Local workspace'}</span>
        </div>
        <div className="flex items-center gap-2.5">
          <button onClick={refresh} className="icon-btn" title="Refresh"><RefreshCw size={15}/></button>
          <button onClick={() => { setShowCreate(true); setError(''); }} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3.5 py-2.5 text-xs font-semibold text-white transition hover:bg-[#115e59]"><Plus size={15}/> New project</button>
        </div>
      </div>
    </header>

    <div className="mx-auto grid max-w-[1440px] grid-cols-1 md:min-h-[calc(100vh-73px)] md:grid-cols-[242px_minmax(0,1fr)]">
      <aside className="border-b border-slate-200 px-4 py-5 md:border-b-0 md:border-r md:px-4">
        <div className="mb-3 flex items-center justify-between px-2"><span className="text-[10px] font-semibold uppercase tracking-[.19em] text-slate-500">Workspaces</span><button onClick={() => setShowCreate(true)} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"><Plus size={14}/></button></div>
        <button onClick={() => { setActiveId(DEMO_ID); setError(''); }} className={`mb-1 flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-[13px] transition ${isDemo ? 'bg-slate-100 text-slate-900' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'}`}><FlaskConical size={15} className={isDemo ? 'text-[#0f766e]' : 'text-slate-500'}/><span className="min-w-0 flex-1 truncate">Demo benchmark</span><span className="text-[10px] text-slate-400">300</span></button>
        {projects.length ? <div className="space-y-1">{projects.map((project) => <button key={project.id} onClick={() => { setActiveId(project.id); setError(''); }} className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-[13px] transition ${!isDemo && activeProject?.id === project.id ? 'bg-slate-100 text-slate-900' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'}`}><FolderKanban size={15} className={!isDemo && activeProject?.id === project.id ? 'text-[#0f766e]' : 'text-slate-500'}/><span className="min-w-0 flex-1 truncate">{project.name}</span><span className="text-[10px] text-slate-400">{project.sources.length}</span></button>)}</div> : <div className="px-2.5 py-3 text-xs leading-5 text-slate-400">Your project spaces will show up here.</div>}
        <div className="my-5 h-px bg-slate-100" />
        <div className="space-y-1 px-1">
          <div className="flex items-center gap-2 px-2 py-2 text-[10px] font-semibold uppercase tracking-[.19em] text-slate-500">Project flow</div>
          {[['01', 'Bring feedback together'], ['02', 'Discover themes'], ['03', 'Review the roadmap'], ['04', 'Launch to GitHub']].map(([n, label], i) => <div key={n} className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-xs text-slate-500"><span className={`font-mono text-[10px] ${i === 0 ? 'text-[#0f766e]' : 'text-slate-300'}`}>{n}</span>{label}</div>)}
        </div>
        <div className="mt-8 rounded-xl border border-slate-200 bg-slate-50 p-3.5"><div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-slate-700"><CircleHelp size={14} className="text-[#0f766e]"/> Your data stays scoped</div><p className="text-[11px] leading-[1.65] text-slate-500">Each project keeps its own source list. Nothing is sent to GitHub without your approval.</p></div>
      </aside>

      <main className="min-w-0 px-5 py-7 md:px-9 md:py-9">
        {isDemo ? demoView : !activeProject ? <div className="mx-auto flex min-h-[70vh] max-w-xl flex-col items-center justify-center text-center">
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-[20px] border border-emerald-700/20 bg-emerald-50 text-[#0f766e]"><FolderKanban size={28}/></div>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-[.22em] text-[#0f766e]">A clearer path from feedback to shipped work</p>
          <h1 className="text-3xl font-semibold tracking-[-.04em] text-slate-900 sm:text-4xl">Start with a project.</h1>
          <p className="mt-3 max-w-md text-sm leading-6 text-slate-600">Bring calls, research docs, and customer feedback into one evidence-backed roadmap. Motif finds the patterns; your team decides what ships.</p>
          <button onClick={() => setShowCreate(true)} className="mt-7 flex items-center gap-2 rounded-lg bg-[#0f766e] px-4 py-3 text-sm font-semibold text-white hover:bg-[#115e59]"><Plus size={16}/> Create your first project</button>
          <div className="mt-10 grid w-full grid-cols-3 gap-3 text-left">{[['Collect', 'Calls and docs'], ['Connect', 'Emergent themes'], ['Ship', 'Human-approved issues']].map(([title, desc], i) => <div key={title} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><span className="font-mono text-[10px] text-slate-400">0{i+1}</span><p className="mt-3 text-xs font-medium text-slate-800">{title}</p><p className="mt-1 text-[10px] text-slate-500">{desc}</p></div>)}</div>
        </div> : <>
          <div className="mb-8 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
            <div><div className="mb-3 flex items-center gap-2 text-[11px] text-slate-500"><span>Projects</span><span>/</span><span className="text-slate-700">{activeProject.name}</span></div><h1 className="text-[28px] font-semibold tracking-[-.045em] text-slate-900 sm:text-[34px]">{activeProject.name}<span className="ml-3 align-middle text-sm font-normal tracking-normal text-slate-400">workspace</span></h1><p className="mt-2 max-w-xl text-[13px] leading-5 text-slate-600">Bring the evidence together. Motif will map recurring needs into themes you can inspect, prioritize, and launch.</p></div>
            <div className="flex flex-wrap items-center gap-2"><button onClick={() => setShowDrive(true)} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100"><HardDrive size={14}/> Add Drive folder</button><button onClick={() => folderInput.current?.click()} disabled={working === 'upload'} title="Import an Obsidian vault or any folder of notes and documents" className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"><FolderOpen size={14}/> Import folder</button><button onClick={() => fileInput.current?.click()} disabled={working === 'upload'} title="PDF, Word, PowerPoint, Excel, Markdown, text, CSV, JSON or .zip" className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-50">{working === 'upload' ? <LoaderCircle size={14} className="animate-spin"/> : <Upload size={14}/>} Upload files</button><button onClick={runAnalysis} disabled={working === 'pipeline' || !sources.length} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3.5 py-2.5 text-xs font-semibold text-white transition hover:bg-[#115e59] disabled:cursor-not-allowed disabled:opacity-40">{working === 'pipeline' ? <LoaderCircle size={14} className="animate-spin"/> : <Sparkles size={14}/>} Analyze feedback</button></div>
            <input ref={fileInput} type="file" multiple accept={UPLOAD_ACCEPT} className="hidden" onChange={onFiles}/>
            <input ref={(element) => { folderInput.current = element; element?.setAttribute('webkitdirectory', ''); }} type="file" multiple className="hidden" onChange={onFiles}/>
          </div>

          {noticeBanner}

          <section className="mb-7 grid grid-cols-1 gap-3 lg:grid-cols-[1.3fr_.7fr]">
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6">
              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"><div><div className="flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-50 text-rose-600"><AudioLines size={15}/></span><span className="text-sm font-semibold text-slate-900">Capture a customer conversation</span></div><p className="mt-2 max-w-md text-xs leading-5 text-slate-500">Record a meeting in your browser and create a transcript file right in this project.</p></div><span className={`inline-flex items-center gap-1.5 self-start rounded-full border px-2.5 py-1 text-[10px] ${recording ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-500'}`}><span className={`h-1.5 w-1.5 rounded-full ${recording ? 'animate-pulse bg-rose-600' : 'bg-slate-300'}`}/>{recording ? 'Recording live' : 'Browser microphone'}</span></div>
              <div className="mt-5 flex flex-col gap-2 sm:flex-row"><input value={meetingName} onChange={(event) => setMeetingName(event.target.value)} className="field flex-1" aria-label="Meeting name" placeholder="Give this conversation a name"/><button onClick={recording ? stopMeeting : startMeeting} className={`flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition ${recording ? 'bg-rose-600 text-white hover:bg-rose-700' : 'bg-[#0f766e] text-white hover:bg-[#115e59]'}`}>{recording ? <><MicOff size={14}/> Stop & save transcript</> : <><Mic size={14}/> Start recording</>}</button></div>
              {(transcribing || transcript) && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3.5"><div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[.17em] text-slate-500"><Radio size={12} className={transcribing ? 'text-rose-600' : 'text-slate-500'}/>{transcribing ? 'Live transcript' : 'Transcript preview'}</div><p className="max-h-28 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700">{transcript || 'Listening… start speaking to see words here.'}</p></div>}
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6"><div className="flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-50 text-blue-700"><Cloud size={15}/></span><span className="text-sm font-semibold text-slate-900">Connect Google Drive</span></div><p className="mt-2 text-xs leading-5 text-slate-500">Choose a project folder to keep research docs and meeting notes in scope.</p><button onClick={() => setShowDrive(true)} className="mt-5 flex items-center gap-2 text-xs font-medium text-slate-700 hover:text-[#0f766e]">Choose a folder <ArrowRight size={14}/></button><p className="mt-3 text-[10px] leading-4 text-slate-400">{activeProject.driveFolder ? 'Folder scope recorded · connector setup still required' : 'Private-by-default: only the folder you choose should be read.'}</p></div>
          </section>

          <section className="mb-7 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_2px_8px_rgba(15,23,42,0.035)]">
            <div className="flex flex-col justify-between gap-3 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:px-6"><div><div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-slate-900">Project sources</h2><span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600">{sources.length}</span></div><p className="mt-1 text-[11px] text-slate-500">Documents, notes, exports and transcripts, split into passages for analysis.</p></div><div className="relative"><Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/><input value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} className="field h-8 w-full pl-8 text-[11px] sm:w-48" placeholder="Find a source"/></div></div>
            {filteredSources.length ? <div className="divide-y divide-slate-100">{filteredSources.map((source) => <div key={source.id} className="flex items-center gap-3 px-5 py-3.5 sm:px-6"><span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${source.kind === 'meeting' ? 'bg-rose-50 text-rose-700' : source.kind === 'drive' ? 'bg-blue-50 text-blue-700' : 'bg-violet-50 text-violet-700'}`}>{source.kind === 'meeting' ? <Headphones size={15}/> : source.kind === 'drive' ? <HardDrive size={15}/> : <FileText size={15}/>}</span><div className="min-w-0 flex-1"><div className="truncate text-xs font-medium text-slate-800">{source.name}</div><div className="mt-1 text-[10px] text-slate-400">{source.kind === 'meeting' ? 'Meeting transcript' : source.kind === 'drive' ? 'Google Drive' : 'Document'} <span className="mx-1">·</span>{new Date(source.createdAt).toLocaleDateString()}{typeof source.passages === 'number' && <><span className="mx-1">·</span>{plural(source.passages, 'passage')}</>}</div></div><span className={`hidden rounded-full px-2 py-1 text-[9px] sm:inline-flex ${source.syncState === 'synced' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{source.syncState === 'synced' ? 'Synced' : 'Saved locally'}</span>{source.content && <button title="Download source file" onClick={() => downloadSource(source)} className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><ArrowDown size={14}/></button>}<button title="Remove from project" onClick={() => removeSource(source)} disabled={Boolean(working)} className="rounded-md p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40">{working === `source:${source.id}` ? <LoaderCircle size={14} className="animate-spin"/> : <Trash2 size={14}/>}</button></div>)}</div> : <div className="flex flex-col items-center px-5 py-10 text-center"><div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-500"><FileText size={18}/></div><p className="text-xs font-medium text-slate-700">{sources.length ? 'No matching files' : 'No sources in this project yet'}</p><p className="mt-1 max-w-sm text-[11px] leading-5 text-slate-400">{sources.length ? 'Try a different search.' : 'Upload interview notes, call transcripts, support-ticket exports or a whole Obsidian vault. PDF, Word, PowerPoint, Excel, Markdown, CSV and .zip all work.'}</p>{!sources.length && <div className="mt-4 flex gap-2"><button onClick={() => fileInput.current?.click()} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-[11px] text-slate-700 hover:bg-slate-100"><Upload size={13}/> Upload files</button><button onClick={() => folderInput.current?.click()} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-[11px] text-slate-700 hover:bg-slate-100"><FolderOpen size={13}/> Import folder</button></div>}</div>}
          </section>

          <section className="mb-7 rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6">
            <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><div className="flex items-center gap-2"><Activity size={15} className="text-[#0f766e]"/><h2 className="text-sm font-semibold text-slate-900">Roadmap signal map</h2></div><p className="mt-1 text-[11px] text-slate-500">Sources → evidence → emergent themes → approved GitHub issue</p></div><button onClick={runAnalysis} disabled={working === 'pipeline' || !sources.length} className="flex items-center gap-2 self-start rounded-lg border border-slate-200 px-3 py-2 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"><Zap size={13}/>{working === 'pipeline' ? 'Analyzing…' : 'Build roadmap'}</button></div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_28px_1fr_28px_1fr_28px_1fr] sm:items-center">{[
              {label:'Feedback sources', count:sources.length, icon:<FileText size={15}/>, sub:'Project inputs', color:'text-slate-700'},
              {label:'Evidence library', count:sources.reduce((total, source) => total + (source.passages ?? 1), 0), icon:<Search size={15}/>, sub:'Passages', color:'text-blue-700'},
              {label:'Discovered themes', count:themes.length, icon:<Sparkles size={15}/>, sub:pendingThemes.length ? `${pendingThemes.length} awaiting review` : 'HDBSCAN clusters', color:'text-violet-700'},
              {label:'GitHub issues', count:themes.filter((theme) => theme.github_issue_url).length, icon:<GitBranch size={15}/>, sub:'Human approved', color:'text-[#0f766e]'},
            ].map((step, index) => <div key={step.label} className="contents"><div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5"><div className={`mb-3 flex items-center gap-2 text-[10px] ${step.color}`}>{step.icon}<span>{step.label}</span></div><div className="flex items-end justify-between"><span className="text-2xl font-semibold tracking-tight text-slate-900">{step.count}</span><span className="mb-1 text-[9px] text-slate-400">{step.sub}</span></div></div>{index < 3 && <ArrowRight size={14} className="hidden justify-self-center text-slate-300 sm:block"/>}{index < 3 && <ArrowDown size={14} className="mx-auto my-[-3px] text-slate-300 sm:hidden"/>}</div>)}</div>
            {!apiOnline && <p className="mt-4 text-[10px] leading-4 text-slate-400">Analysis and GitHub dispatch require the Motif API, database, and model/GitHub credentials. Your project sources are currently saved in this browser.</p>}
          </section>

          {roadmapSection}
        </>}
      </main>
    </div>

    {showCreate && <div className="modal-backdrop"><form onSubmit={createProject} className="modal-card"><div className="flex items-start justify-between"><div><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 text-[#0f766e]"><FolderKanban size={17}/></div><h2 className="text-lg font-semibold text-slate-900">Create a project</h2><p className="mt-1 text-xs leading-5 text-slate-500">Make a workspace for the feedback and roadmap you want to bring together.</p></div><button type="button" onClick={() => setShowCreate(false)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div><label className="mt-6 block text-[11px] font-medium text-slate-600">Project name<input autoFocus value={newName} onChange={(event) => setNewName(event.target.value)} className="field mt-2 w-full" placeholder="e.g. Project Atlas" required/></label><label className="mt-4 block text-[11px] font-medium text-slate-600">GitHub repository <span className="font-normal text-slate-400">(optional, owner/repo)</span><input value={newRepo} onChange={(event) => setNewRepo(event.target.value)} className="field mt-2 w-full" placeholder="acme/product"/></label><p className="mt-3 text-[10px] leading-4 text-slate-400">Projects and source metadata are stored in this browser. Issues use this project repository or fall back to the backend&apos;s configured repository.</p><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setShowCreate(false)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Cancel</button><button className="rounded-lg bg-[#0f766e] px-4 py-2 text-xs font-semibold text-white">Create project</button></div></form></div>}

    {showDrive && <div className="modal-backdrop"><form onSubmit={saveDriveScope} className="modal-card"><div className="flex items-start justify-between"><div><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><HardDrive size={17}/></div><h2 className="text-lg font-semibold text-slate-900">Add a Drive folder</h2><p className="mt-1 text-xs leading-5 text-slate-500">Scope this project to one folder, not your whole Drive.</p></div><button type="button" onClick={() => setShowDrive(false)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div><label className="mt-6 block text-[11px] font-medium text-slate-600">Google Drive folder URL or ID<input value={folderUrl} onChange={(event) => setFolderUrl(event.target.value)} className="field mt-2 w-full" placeholder="https://drive.google.com/drive/folders/…" required/></label><div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] leading-[1.7] text-slate-600"><span className="font-medium text-amber-800">Connector setup required.</span> This build does not have Google OAuth credentials or a Drive sync endpoint. The folder scope will be noted locally, but no Drive files are accessed yet. Enable the Google Drive connector on the backend before using it with sensitive project data.</div><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setShowDrive(false)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Cancel</button><button className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white">Save folder scope</button></div></form></div>}

    {reviewTheme && <div className="modal-backdrop"><div className="modal-card max-h-[85vh] overflow-y-auto"><div className="flex items-start justify-between"><span className="text-[10px] uppercase tracking-[.18em] text-[#0f766e]">Evidence review</span><button onClick={() => setReviewTheme(null)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div>
      <label className="mt-3 block text-[11px] font-medium text-slate-600">Theme title<input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} className="field mt-1.5 w-full text-sm font-semibold text-slate-900"/></label>
      <label className="mt-3 block text-[11px] font-medium text-slate-600">Problem summary<textarea value={editSummary} onChange={(event) => setEditSummary(event.target.value)} rows={3} className="field mt-1.5 w-full resize-y text-xs leading-5 text-slate-700"/></label>
      {(editTitle.trim() !== reviewTheme.title || editSummary.trim() !== reviewTheme.summary) && <p className="mt-2 text-[10px] text-amber-700">Edited — this approval will count as “edited” in the acceptance rate.</p>}
      <div className="mt-5 flex flex-wrap gap-4 border-y border-slate-200 py-3 text-[11px] text-slate-600">{reviewTheme.revenue_at_risk > 0 && <><span>${reviewTheme.revenue_at_risk.toLocaleString()} ARR at risk</span><span>{plural(reviewTheme.affected_accounts_count, 'account')}</span></>}{reviewTheme.mention_count ? <span>{plural(reviewTheme.mention_count, 'mention')}</span> : null}{reviewTheme.source_count ? <span>{plural(reviewTheme.source_count, 'source')}</span> : null}</div><div className="mt-5 space-y-3">{reviewTheme.cited_quotes?.length ? reviewTheme.cited_quotes.map((quote, index) => <blockquote key={index} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-700">“{quote.quote_text}”<span className="mt-2 block text-[10px] text-slate-400">{[quote.customer_id, quote.customer_id ? quote.customer_tier : null, quote.source_name].filter(Boolean).join(' · ') || 'Customer'}</span></blockquote>) : <p className="text-xs text-slate-500">No evidence quotes have been attached.</p>}</div>
      <div className="sticky -bottom-5 -mx-5 -mb-5 mt-6 flex flex-wrap justify-end gap-2 border-t border-slate-100 bg-white px-5 pb-5 pt-3 sm:-bottom-6 sm:-mx-6 sm:-mb-6 sm:px-6 sm:pb-6"><button onClick={() => setReviewTheme(null)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Close</button><button onClick={() => dismissTheme(reviewTheme)} disabled={Boolean(working)} className="rounded-lg border border-rose-200 px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50">Reject</button><button onClick={() => launchTheme(reviewTheme, { title: editTitle, summary: editSummary })} disabled={Boolean(working) || !editTitle.trim()} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><GitBranch size={14}/> Approve & create issue</button></div></div></div>}

    {prdTheme && <div className="modal-backdrop"><div className="modal-card max-h-[85vh] overflow-y-auto"><div className="flex items-start justify-between"><div><span className="text-[10px] uppercase tracking-[.18em] text-[#0f766e]">Generated PRD</span><h2 className="mt-2 text-lg font-semibold text-slate-900">{prdTheme.title}</h2></div><button onClick={() => setPrdTheme(null)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div>
      {prdTheme.github_issue_url ? <a href={prdTheme.github_issue_url} target="_blank" rel="noreferrer" className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs text-emerald-900 hover:bg-emerald-100"><GitBranch size={14}/> GitHub issue #{prdTheme.github_issue_number} created <ExternalLink size={12}/></a> : <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[11px] leading-5 text-amber-900">Not sent to GitHub. Set GITHUB_TOKEN, GITHUB_REPO_OWNER and GITHUB_REPO_NAME in .env to create real issues.</div>}
      <pre className="mt-4 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-[11px] leading-5 text-slate-700">{prdTheme.prd_markdown || 'No PRD text was returned for this theme.'}</pre>
      <div className="mt-5 flex justify-end gap-2">{prdTheme.prd_markdown && <button onClick={() => copyPrd(prdTheme.prd_markdown || '')} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700 hover:bg-slate-100"><Clipboard size={13}/>{copied ? 'Copied' : 'Copy PRD'}</button>}<button onClick={() => setPrdTheme(null)} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">Done</button></div></div></div>}
  </div>;
}
