'use client';

import { ChangeEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowDown, Check, Clipboard, ExternalLink, FolderOpen, LoaderCircle, Mic, MicOff, Plus, RefreshCw, Search, Trash2, Upload, Users, X,
} from 'lucide-react';
import { SIGN_IN_REQUIRED, approveTheme, changeIssueType, deleteSource, fetchMetrics, fetchProjects, fetchPipelineStatus, fetchSources, fetchThemes, ingestSource, rejectTheme, runPipeline, saveProject, uploadSources } from '@/utils/api';
import { authEnabled, getSupabase } from '@/utils/supabase';
import type { PipelineProgress } from '@/utils/api';
import Connectors from '@/components/Connectors';
import LiveInbox from '@/components/LiveInbox';
import ShareProject from '@/components/ShareProject';
import { RankingKey, ScoreProof, ScoreStrip } from '@/components/ScoreBreakdown';
import ThemePicker from '@/components/ThemePicker';
import type { EvalMetrics, InboxItem, IssueType, Project, ProjectSource, Theme, ThemeActivity, UploadFileResult, UploadedSource } from '@/utils/types';

const STORE_KEY = 'motif-project-workspaces-v1';
const REPO_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
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
  id: source.id, serverId: source.id, name: source.connection_id ? source.title : (source.path?.split('/').pop() || source.title), kind: 'document',
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

// "Approved by bob@acme.com, 5 min ago"
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
  if (item.action === 'type_changed') return `Marked as ${item.title || 'another kind of problem'} by ${item.by}${item.at ? `, ${since(item.at)}` : ''}`;
  const verb = item.action === 'approved' && item.changed_title ? 'Approved with edits' : item.action.charAt(0).toUpperCase() + item.action.slice(1);
  return `${verb} by ${item.by}${item.at ? `, ${since(item.at)}` : ''}`;
}

// "Bug: 4 of 6 messages use words like “crashes”, “fails”" or "Set by a PM (the words suggested Feature request)"
function typeReason(issue: IssueType) {
  if (issue.source === 'pm') return `Set by a PM${issue.detected && issue.detected !== issue.type ? ` (the words suggested ${issue.detected === 'ux' ? 'UX friction' : issue.detected === 'feature' ? 'a feature request' : issue.detected})` : ''}.`;
  if (issue.type === 'general') return 'No single kind of problem stands out in the words used.';
  const terms = [...new Set(issue.evidence.map((e) => `“${e.term}”`))].slice(0, 3).join(', ');
  return `${issue.counts[issue.type] ?? issue.evidence.length} of ${issue.messages} messages use words like ${terms}.`;
}

function makeId() { return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`; }
function readProjects(key: string): Project[] {
  try { const value = localStorage.getItem(key); return value ? JSON.parse(value) as Project[] : []; } catch { return []; }
}

// Projects live on the server for a signed-in user. Save any that only exist in this browser,
// then show the server's list with the sources this browser already knows about.
async function syncWithServer(local: Project[]): Promise<Project[]> {
  let server = await fetchProjects();
  const onServer = new Set(server.map((project) => project.id));
  const pending = local.filter((project) => !onServer.has(project.id));
  const failed: Project[] = [];
  for (const project of pending) {
    try { await saveProject(project); } catch (cause) {
      // A shared project you were removed from (or left) is not yours to recreate: drop it from this browser
      if (cause instanceof Error && /not found|owner/i.test(cause.message)) continue;
      failed.push(project);
    }
  }
  if (pending.length > failed.length) server = await fetchProjects();
  const cached = new Map(local.map((project) => [project.id, project]));
  const merged = server.map((project) => {
    const known = cached.get(project.id);
    return { id: project.id, name: project.name, repo: project.github_repo || '', driveFolder: known?.driveFolder, sources: known?.sources || [], role: project.role || 'owner', ownerEmail: project.owner_email } as Project;
  });
  return [...merged, ...failed];
}

export default function Workspace() {
  const router = useRouter();
  const [userEmail, setUserEmail] = useState('');
  const [storeKey, setStoreKey] = useState(STORE_KEY);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState('');
  const [ready, setReady] = useState(false);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [apiOnline, setApiOnline] = useState(false);
  const [newName, setNewName] = useState('');
  const [newRepo, setNewRepo] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [sourceSearch, setSourceSearch] = useState('');
  const [rankingProfile, setRankingProfile] = useState<'b2b_saas' | 'dev_tools'>('b2b_saas');
  const [showShare, setShowShare] = useState(false);
  const [tab, setTab] = useState<'roadmap' | 'sources' | 'approved'>('roadmap');
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
  const [progress, setProgress] = useState<PipelineProgress | null>(null);
  const [lastRunSeconds, setLastRunSeconds] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  // Live inbox: themes a new message just changed, and where each row stood before (so rows can slide to their new place)
  const [flash, setFlash] = useState<Record<string, { from?: number; to?: number }>>({});
  const rowTops = useRef<Map<string, number>>(new Map());
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<BrowserRecognition | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunks = useRef<Blob[]>([]);
  const transcriptRef = useRef('');

  const isDemo = activeId === DEMO_ID;
  const activeProject = projects.find((project) => project.id === activeId) || projects[0];
  // Your role on the open project: owners manage people and tools, editors act on themes, viewers read
  const role = activeProject?.role || 'owner';
  const canEdit = role !== 'viewer';
  const isOwner = role === 'owner';
  // The shared demo is read-only once people sign in: decisions there would change everyone's numbers
  const demoLocked = isDemo && authEnabled;
  const sources = activeProject?.sources || [];
  const filteredSources = sources.filter((source) => source.name.toLowerCase().includes(sourceSearch.toLowerCase()));
  const pendingThemes = useMemo(() => themes.filter((theme) => theme.status === 'pending_review'), [themes]);
  const approvedThemes = useMemo(() => themes.filter((theme) => theme.status === 'approved'), [themes]);
  const rejectedCount = themes.filter((theme) => theme.status === 'rejected').length;

  useEffect(() => {
    // Browser storage is read after hydration to avoid an SSR/client mismatch.
    let cancelled = false;
    const start = async () => {
      let key = STORE_KEY;
      let loaded: Project[] = [];
      let legacy = false;
      const supabase = getSupabase();
      if (supabase) {
        const { data } = await supabase.auth.getSession();
        const user = data.session?.user;
        if (!user) { router.replace('/login'); return; }
        if (cancelled) return;
        key = `${STORE_KEY}:${user.id}`;
        setUserEmail(user.email || '');
        loaded = readProjects(key);
        if (!loaded.length) { loaded = readProjects(STORE_KEY); legacy = loaded.length > 0; }
        try {
          // Do not let a slow or missing backend keep the spinner up forever
          const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timeout')), 10000));
          loaded = await Promise.race([syncWithServer(loaded), timeout]);
          setApiOnline(true);
        } catch { /* offline or slow: keep what this browser has */ }
        // Projects from before accounts existed are removed from the shared key only after they are saved
        if (legacy) { try { localStorage.removeItem(STORE_KEY); } catch { /* ignore */ } }
      } else {
        loaded = readProjects(key);
      }
      if (cancelled) return;
      setStoreKey(key);
      setProjects(loaded);
      setActiveId(loaded[0]?.id || DEMO_ID);
      setReady(true);
    };
    start().catch(() => { if (!cancelled) { setProjects([]); setActiveId(DEMO_ID); setReady(true); } });
    return () => { cancelled = true; };
  }, [router]);

  useEffect(() => {
    const goToLogin = () => router.replace('/login');
    window.addEventListener(SIGN_IN_REQUIRED, goToLogin);
    return () => window.removeEventListener(SIGN_IN_REQUIRED, goToLogin);
  }, [router]);

  const signOut = async () => {
    await getSupabase()?.auth.signOut();
    router.replace('/login');
  };

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

  // A message reached the live inbox (typed here, or sent from another tool): re-read the ranking, slide rows to
  // their new places and mark the themes that changed
  useLayoutEffect(() => {
    // Runs after the new order is on screen: move each row from where it was to where it is now
    const before = rowTops.current;
    if (!before.size) return;
    rowTops.current = new Map();
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    document.querySelectorAll<HTMLElement>('[data-theme-row]').forEach((row) => {
      const was = before.get(row.dataset.themeRow || '');
      if (was === undefined) return;
      const shift = was - row.getBoundingClientRect().top;
      if (Math.abs(shift) > 2) row.animate([{ transform: `translateY(${shift}px)` }, { transform: 'none' }], { duration: 520, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
    });
  }, [themes]);

  const liveArrived = (entries: InboxItem[]) => {
    const marks: Record<string, { from?: number; to?: number }> = {};
    for (const entry of entries) {
      const match = entry.match;
      if (match.status !== 'joined') continue;
      if (match.theme_id && !marks[match.theme_id]) marks[match.theme_id] = {};
      for (const moved of match.moved ?? []) {
        const mark = marks[moved.theme_id];
        marks[moved.theme_id] = { from: mark?.from ?? moved.from, to: moved.to };
      }
    }
    rowTops.current = new Map(Array.from(document.querySelectorAll<HTMLElement>('[data-theme-row]')).map((row) => [row.dataset.themeRow || '', row.getBoundingClientRect().top]));
    fetchThemes(isDemo ? undefined : activeProject?.id).then((value) => {
      setThemes(value); setApiOnline(true); setFlash(marks);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlash({}), 9000);
    }).catch(() => { rowTops.current = new Map(); });
  };

  useEffect(() => {
    if (ready) { try { localStorage.setItem(storeKey, JSON.stringify(projects)); } catch { /* storage full or blocked */ } }
  }, [projects, ready, storeKey]);

  useEffect(() => () => {
    recognitionRef.current?.stop?.();
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  const updateProject = (id: string, updater: (project: Project) => Project) => {
    setProjects((current) => current.map((project) => project.id === id ? updater(project) : project));
  };

  // Re-read a project's sources from the server (after a tool sync added, updated or removed some)
  const refreshServerSources = (projectId: string) => fetchSources(projectId).then((server) => updateProject(projectId, (project) => {
    const local = new Map(project.sources.filter((source) => source.serverId).map((source) => [source.serverId as string, source]));
    const synced = server.map((source) => local.get(source.id) ? { ...(local.get(source.id) as ProjectSource), passages: source.passages } : fromServer(source));
    return { ...project, sources: [...synced, ...project.sources.filter((source) => !source.serverId)] };
  })).catch(() => undefined);

  const createProject = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    const repo = newRepo.trim();
    if (repo && !REPO_PATTERN.test(repo)) { setError('Write the repository as owner/repo, for example acme/product.'); return; }
    const project: Project = { id: makeId(), name, repo, sources: [] };
    try { await saveProject(project); setApiOnline(true); } catch (failure) {
      if (authEnabled) { setError(failure instanceof Error ? failure.message : 'Could not save the project. Check that the API is running.'); return; }
    }
    setProjects((existing) => [...existing, project]);
    setActiveId(project.id);
    setNewName(''); setNewRepo(''); setShowCreate(false);
    setNotice(`Created “${name}”. Add sources, then analyze them.`); setTab('sources');
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
      const result = await runPipeline(activeProject.id, setProgress, rankingProfile);
      const updated = await fetchThemes(activeProject.id); setThemes(updated); setApiOnline(true); setTab('roadmap');
      const created = result.themes_created ?? updated.length;
      const took = typeof result.duration_seconds === 'number' ? ` in ${result.duration_seconds}s` : '';
      setNotice(created
        ? `Analysis finished${took}. ${plural(created, 'theme')} ready to review.`
        : `Analysis finished${took}, but no themes yet. A theme needs at least 4 passages about the same problem, so add more sources and analyze again.`);
    } catch (cause) { setApiOnline(false); setError(cause instanceof Error ? cause.message : API_HINT); }
    finally { setWorking(''); setProgress(null); }
  };

  const runDemoAnalysis = async () => {
    setWorking('pipeline'); setError(''); setNotice('');
    try {
      const result = await runPipeline(undefined, setProgress);
      const [updated, latest] = await Promise.all([fetchThemes(), fetchMetrics()]);
      setThemes(updated); setMetrics(latest); setApiOnline(true);
      if (typeof result.duration_seconds === 'number') setLastRunSeconds(result.duration_seconds);
      setNotice(`Analysis finished${typeof result.duration_seconds === 'number' ? ` in ${result.duration_seconds}s` : ''}. ${result.themes_created ?? updated.length} themes found in the demo data.`);
    } catch (cause) { setApiOnline(false); setError(cause instanceof Error ? cause.message : API_HINT); }
    finally { setWorking(''); setProgress(null); }
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
      const preview = result.audit_logged === false;
      const approved: Theme = { ...theme, title, summary, status: preview ? theme.status : 'approved', github_issue_url: result.github_issue_url, github_issue_number: result.github_issue_number, prd_markdown: result.prd_markdown };
      if (!preview) setThemes((existing) => existing.map((item) => item.id === theme.id ? approved : item));
      setReviewTheme(null);
      setPrdTheme(approved);
      setNotice(preview ? 'This is a preview of the PRD. The demo is read-only, so nothing was saved and no issue was opened.' : result.github_issue_url ? `Approved. Issue #${result.github_issue_number} is open in GitHub.` : `Approved and PRD written. ${result.github_message ?? 'No GitHub issue was opened.'}`);
      if (isDemo) fetchMetrics().then(setMetrics).catch(() => undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create GitHub issue. Check the GitHub configuration.');
      if (cause instanceof Error && cause.message.startsWith('Already')) { setReviewTheme(null); fetchThemes(isDemo ? undefined : activeProject?.id).then(setThemes).catch(() => undefined); }
    }
    finally { setWorking(''); }
  };

  // A PM corrects the kind of problem: the backend re-weights it and re-ranks every theme in the project
  const retypeTheme = async (theme: Theme, issueType: string) => {
    setWorking(`type:${theme.id}`); setError('');
    try {
      const result = await changeIssueType(theme.id, issueType);
      const updated = await fetchThemes(isDemo ? undefined : activeProject?.id);
      setThemes(updated);
      const fresh = updated.find((item) => item.id === theme.id);
      if (fresh) setReviewTheme(fresh);
      setNotice(`Marked as ${fresh?.score_breakdown?.issue_type?.label ?? issueType}. It now ranks ${result.rank} of ${result.of}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not change the kind of problem.'); }
    finally { setWorking(''); }
  };

  const dismissTheme = async (theme: Theme) => {
    setWorking(theme.id); setError('');
    try {
      await rejectTheme(theme.id);
      setThemes((existing) => existing.map((item) => item.id === theme.id ? { ...item, status: 'rejected' } : item));
      setReviewTheme(null);
      setNotice(`Rejected “${theme.title}”. It stays in the history.`);
      if (isDemo) fetchMetrics().then(setMetrics).catch(() => undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reject this theme.');
      if (cause instanceof Error && cause.message.startsWith('Already')) { setReviewTheme(null); fetchThemes(isDemo ? undefined : activeProject?.id).then(setThemes).catch(() => undefined); }
    }
    finally { setWorking(''); }
  };

  const copyPrd = async (markdown: string) => {
    try { await navigator.clipboard.writeText(markdown); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { setError('Could not copy to the clipboard. Select the text and copy it instead.'); }
  };


  const downloadSource = (source: ProjectSource) => {
    const blob = new Blob([source.content], { type: 'text/markdown' }); const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = source.name; link.click(); URL.revokeObjectURL(url);
  };


  const STAGES = [['embedding', 'Reading passages'], ['clustering', 'Finding patterns'], ['labelling', 'Naming themes'], ['saving', 'Saving']] as const;
  const stageIndex = progress?.stage ? STAGES.findIndex(([key]) => key === progress.stage) : -1;
  const stageFraction = progress && progress.total > 0 ? Math.min(progress.done / progress.total, 1) : 0;
  const percent = progress?.stage ? Math.round(((Math.max(stageIndex, 0) + (progress.stage === 'labelling' ? stageFraction : 0)) / STAGES.length) * 100) : 0;

  const progressPanel = working === 'pipeline' ? (
    <div className="panel mb-5 px-4 py-3.5" role="status" aria-live="polite">
      <div className="flex items-center justify-between gap-3 text-[13px]">
        <span className="flex items-center gap-2 font-medium text-ink">
          <LoaderCircle size={14} className="animate-spin text-link"/>
          {progress?.stage ? STAGES[stageIndex][1] : 'Starting the analysis'}
          {progress?.stage === 'labelling' && progress.total > 0 ? ` (${progress.done} of ${progress.total} themes)` : ''}
        </span>
        <span className="tnum text-muted">{progress?.elapsed_seconds != null ? `${Math.round(progress.elapsed_seconds)}s` : ''}</span>
      </div>
      <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-paper"><div className="h-full rounded-full bg-action transition-all duration-500" style={{ width: `${Math.max(percent, 4)}%` }}/></div>
      <ol className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
        {STAGES.map(([key, label], index) => <li key={key} className={index < stageIndex ? 'text-link' : index === stageIndex ? 'font-medium text-ink' : ''}>{index < stageIndex ? <Check size={12} className="mr-1 inline"/> : null}{label}</li>)}
      </ol>
    </div>
  ) : null;

  const noticeBanner = (<>
    {progressPanel}
    {(notice || error) ? (
      <div role={error ? 'alert' : 'status'} className={`mb-5 flex items-start justify-between gap-3 rounded-md border-l-[3px] px-4 py-3 text-[13px] leading-relaxed ${error ? 'border-danger bg-danger-soft text-danger' : 'border-action bg-action-soft text-ink'}`}>
        <p>{error || notice}</p>
        <button onClick={() => { setNotice(''); setError(''); }} aria-label="Dismiss" className="icon-btn -my-1 -mr-2 h-7 w-7"><X size={14}/></button>
      </div>
    ) : null}
  </>);

  const whoSaid = (quote: NonNullable<Theme['cited_quotes']>[number]) => [quote.customer_id, quote.source_name].filter(Boolean).join(', ') || 'From your sources';

  // One theme in the ranked list: rank, title, the strongest quote, the parameters, and the decisions
  const themeRow = (theme: Theme, index: number) => {
    const rank = theme.score_breakdown?.rank ?? index + 1;
    const quote = theme.cited_quotes?.[0];
    const moreQuotes = (theme.cited_quotes?.length || 0) - 1;
    const last = theme.activity?.[0];
    return (
      <li key={theme.id} data-theme-row={theme.id} className={`grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 px-4 py-6 sm:grid-cols-[2.5rem_minmax(0,1fr)] sm:px-7 ${index ? 'border-t border-rule' : ''} ${flash[theme.id] ? 'live-flash' : ''}`}>
        <span className="tnum pt-0.5 text-[22px] font-semibold leading-none text-faint" aria-label={`Rank ${rank}`}>{rank}</span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <h3 className="text-[16px] font-semibold leading-snug text-ink">
              {theme.title}
              {theme.score_breakdown?.issue_type && <span title={typeReason(theme.score_breakdown.issue_type)} data-testid="issue-type" className={`ml-2 inline-block translate-y-[-1px] rounded border px-1.5 py-px align-middle text-[12px] font-medium ${theme.score_breakdown.issue_type.type === 'security' ? 'border-danger/40 text-danger' : 'border-rule text-muted'}`}>{theme.score_breakdown.issue_type.label}{theme.score_breakdown.issue_type.source === 'pm' ? ' (set by PM)' : ''}</span>}
            </h3>
            {typeof theme.priority_score === 'number' && <span className="tnum text-[13px] text-muted"><span className="text-[20px] font-semibold text-ink">{Math.round(theme.priority_score)}</span> / 100</span>}
          </div>
          <p className="mt-1 max-w-[70ch] text-muted">{theme.summary}</p>
          {!theme.score_breakdown && <p className="mt-1 text-[13px] text-muted">{plural(theme.mention_count || 0, 'mention')} from {plural(theme.source_count || 0, 'source')}{theme.revenue_at_risk > 0 ? `, $${theme.revenue_at_risk.toLocaleString('en-US')} a year at risk` : ''}. Analyze again to see how it ranks.</p>}
          {quote && (
            <figure className="mt-4 max-w-[68ch]">
              <blockquote className="quote">“<span className="marked">{quote.quote_text}</span>”</blockquote>
              <figcaption className="mt-1.5 text-[13px] text-muted">{whoSaid(quote)}{moreQuotes > 0 ? `, and ${plural(moreQuotes, 'more verified quote')}` : ''}</figcaption>
            </figure>
          )}
          {flash[theme.id] && (
            <p className="mt-3 text-[13px] font-medium text-link" data-testid="live-chip">
              {flash[theme.id].from !== undefined && flash[theme.id].to !== undefined && flash[theme.id].from !== flash[theme.id].to
                ? `${(flash[theme.id].to as number) < (flash[theme.id].from as number) ? 'Moved up' : 'Moved down'}: #${flash[theme.id].from} to #${flash[theme.id].to}, after a new message`
                : 'A new message joined this theme'}
            </p>
          )}
          <ScoreStrip breakdown={theme.score_breakdown}/>
          <div className="mt-4 flex flex-wrap items-center gap-x-1.5 gap-y-2">
            {demoLocked
              ? <button onClick={() => launchTheme(theme)} disabled={Boolean(working)} title="Shows the PRD Motif would write; nothing is saved" className="btn">{working === theme.id && <LoaderCircle size={14} className="animate-spin"/>} Preview PRD</button>
              : <button onClick={() => launchTheme(theme)} disabled={Boolean(working) || !canEdit} title="Writes the PRD and opens a GitHub issue" className="btn">{working === theme.id ? <LoaderCircle size={14} className="animate-spin"/> : <Check size={14}/>} Approve</button>}
            <button onClick={() => openReview(theme)} className="btn-text">Open evidence</button>
            {!demoLocked && <button onClick={() => dismissTheme(theme)} disabled={Boolean(working) || !canEdit} className="btn-danger">Reject</button>}
            {last && <span className="w-full text-[13px] text-muted sm:ml-auto sm:w-auto" data-testid="theme-activity">{describeActivity(last)}</span>}
          </div>
        </div>
      </li>
    );
  };

  // On wide screens the ranking sits beside the live inbox, so you can watch rows move while you type
  const roadmapPanel = (<div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
    <div className="xl:order-2 xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto xl:overflow-x-hidden">
      <LiveInbox key={activeId} projectId={isDemo ? undefined : activeProject?.id} onArrived={liveArrived}/>
    </div>
    <section className="panel overflow-hidden xl:order-1" aria-label="Themes to review">
      <RankingKey breakdown={pendingThemes.find((theme) => theme.score_breakdown)?.score_breakdown}/>
      {pendingThemes.length ? (() => {
        const fixFirst = pendingThemes.filter((theme) => theme.score_breakdown?.lane === 'fix_first');
        const ranked = pendingThemes.filter((theme) => theme.score_breakdown?.lane !== 'fix_first');
        if (!fixFirst.length) return <ol>{ranked.map(themeRow)}</ol>;
        return <>
          <div className="border-b border-rule bg-danger-soft px-5 py-2.5 text-[13px] sm:px-7" data-testid="fix-first"><span className="font-semibold text-danger">Fix first</span><span className="text-muted">: security problems come before everything else, whatever their score.</span></div>
          <ol>{fixFirst.map(themeRow)}</ol>
          {ranked.length > 0 && <div className="border-y border-rule bg-paper px-5 py-2.5 text-[13px] font-semibold text-ink sm:px-7">Ranked by score</div>}
          <ol>{ranked.map(themeRow)}</ol>
        </>;
      })() : (
        <div className="px-5 py-12 text-center sm:px-7">
          <p className="font-medium text-ink">{themes.length ? 'Nothing left to review' : 'No themes yet'}</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-muted">{themes.length ? 'Every theme has a decision. Approved ones are listed under Approved.' : isDemo ? 'Click Analyze feedback to group the demo data into themes.' : 'Add sources, then click Analyze feedback. A theme needs at least four passages about the same problem.'}</p>
          {!themes.length && !isDemo && <button onClick={() => setTab('sources')} className="btn mt-4">Add sources</button>}
        </div>
      )}
    </section>
  </div>);

  const approvedPanel = (
    <section className="panel overflow-hidden" aria-label="Approved themes">
      {approvedThemes.length ? <ul>{approvedThemes.map((theme, index) => {
        const decided = theme.activity?.find((item) => item.action === 'approved');
        return (
          <li key={theme.id} className={`flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:px-7 ${index ? 'border-t border-rule' : ''}`}>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-ink">{theme.title}</p>
              <p className="text-[13px] text-muted">
                {theme.github_issue_url ? <a href={theme.github_issue_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-link hover:underline">Issue #{theme.github_issue_number} <ExternalLink size={12}/></a> : 'PRD written, no GitHub issue'}
                {decided ? `. ${describeActivity(decided)}` : ''}
              </p>
            </div>
            <button onClick={() => setPrdTheme(theme)} className="btn self-start sm:self-auto">View PRD</button>
          </li>
        );
      })}</ul> : <p className="px-5 py-12 text-center text-muted sm:px-7">Nothing approved yet. Approving a theme writes its PRD and opens a GitHub issue.</p>}
      {rejectedCount > 0 && <p className="border-t border-rule px-5 py-3 text-[13px] text-muted sm:px-7">{plural(rejectedCount, 'theme')} rejected. Rejections stay in the history.</p>}
    </section>
  );

  const sourceKind = (source: ProjectSource) => source.kind === 'meeting' ? 'Recorded conversation' : source.kind === 'drive' ? 'Google Drive' : 'Document';
  const sourcesPanel = activeProject ? (
    <div className="space-y-5">
      <section className="panel overflow-hidden" aria-label="Files and notes">
        <div className="flex flex-col gap-3 border-b border-rule px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">Files and notes</h2>
            <p className="text-[13px] text-muted">PDF, Word, PowerPoint, Excel, Markdown, CSV or .zip. A whole folder works too, such as an Obsidian vault.</p>
          </div>
          <div className="flex shrink-0 gap-2">
            <button onClick={() => fileInput.current?.click()} disabled={working === 'upload' || !canEdit} className="btn">{working === 'upload' ? <LoaderCircle size={14} className="animate-spin"/> : <Upload size={14}/>} Upload files</button>
            <button onClick={() => folderInput.current?.click()} disabled={working === 'upload' || !canEdit} className="btn"><FolderOpen size={14}/> Import folder</button>
          </div>
        </div>
        {sources.length > 6 && (
          <div className="relative border-b border-rule px-5 py-2.5 sm:px-7">
            <Search size={14} className="pointer-events-none absolute left-8 top-1/2 -translate-y-1/2 text-faint sm:left-10"/>
            <input value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} aria-label="Find a source" placeholder="Find a source" className="field w-full pl-9! sm:w-72"/>
          </div>
        )}
        {filteredSources.length ? <ul>{filteredSources.map((source, index) => (
          <li key={source.id} className={`flex items-center gap-3 px-5 py-3 sm:px-7 ${index ? 'border-t border-rule' : ''}`}>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-ink">{source.name}</p>
              <p className="text-[13px] text-muted">{sourceKind(source)}{typeof source.passages === 'number' ? `, ${plural(source.passages, 'passage')}` : ''}, added {new Date(source.createdAt).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}{source.syncState === 'synced' ? '' : '. Only in this browser until you analyze'}</p>
            </div>
            {source.content && <button title="Download" aria-label={`Download ${source.name}`} onClick={() => downloadSource(source)} className="icon-btn"><ArrowDown size={15}/></button>}
            <button title="Remove from project" aria-label={`Remove ${source.name}`} onClick={() => removeSource(source)} disabled={Boolean(working) || !canEdit} className="icon-btn hover:text-danger">{working === `source:${source.id}` ? <LoaderCircle size={15} className="animate-spin"/> : <Trash2 size={15}/>}</button>
          </li>
        ))}</ul> : <p className="px-5 py-10 text-center text-muted sm:px-7">{sources.length ? 'No source matches that search.' : 'No sources yet. Upload interview notes, call transcripts or support exports, or connect a tool below.'}</p>}
      </section>

      <Connectors role={role} projectId={activeProject.id} projectName={activeProject.name} open={showConnect} onClose={() => setShowConnect(false)} onSynced={() => refreshServerSources(activeProject.id)} onMessage={(text, isError) => { if (isError) { setError(text); setNotice(''); } else { setNotice(text); setError(''); } }} />

      <section className="panel px-5 py-4 sm:px-7" aria-label="Record a conversation">
        <h2 className="text-[15px] font-semibold text-ink">Record a conversation</h2>
        <p className="text-[13px] text-muted">Transcribes in your browser (Chrome or Edge) and saves the transcript here as a source.</p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input value={meetingName} onChange={(event) => setMeetingName(event.target.value)} className="field flex-1" aria-label="Conversation name" placeholder="Name this conversation"/>
          <button onClick={recording ? stopMeeting : startMeeting} disabled={!canEdit && !recording} className={recording ? 'btn border-danger text-danger' : 'btn'}>{recording ? <><MicOff size={14}/> Stop and save</> : <><Mic size={14}/> Start recording</>}</button>
        </div>
        {(transcribing || transcript) && <div className="mt-3 rounded-md bg-paper px-3.5 py-3"><p className="text-[12px] font-medium text-muted">{transcribing ? 'Listening' : 'Transcript'}</p><p className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{transcript || 'Start speaking to see the words here.'}</p></div>}
      </section>
      <input ref={fileInput} type="file" multiple accept={UPLOAD_ACCEPT} className="hidden" onChange={onFiles}/>
      <input ref={(element) => { folderInput.current = element; element?.setAttribute('webkitdirectory', ''); }} type="file" multiple className="hidden" onChange={onFiles}/>
    </div>
  ) : null;

  const metricCells = [
    { label: 'Theme precision (top 3)', value: pct(metrics?.precision_at_3), target: '90% or more', met: meets(metrics?.precision_at_3, 90), measured: metrics?.precision_at_3 != null, sub: metrics?.precision_at_3 == null ? 'Measured after the first analysis' : 'Top 3 themes against the true top 3' },
    { label: 'Approved without edits', value: pct(metrics?.acceptance_rate), target: '70% or more', met: meets(metrics?.acceptance_rate, 70), measured: metrics?.acceptance_rate != null, sub: metrics?.acceptance_rate == null ? 'No decisions yet' : `Across ${plural(metrics.pm_decisions_count, 'decision')}` },
    { label: 'Quotes verified', value: pct(metrics?.citation_validity), target: '100%', met: meets(metrics?.citation_validity, 100), measured: metrics?.citation_validity != null, sub: metrics?.citation_validity == null ? 'No quotes stored yet' : `${metrics.verified_quotes_count} of ${metrics.total_quotes_count} found word for word` },
    { label: 'Analysis time', value: lastRunSeconds === null ? '—' : `${lastRunSeconds}s`, target: 'under 90s', met: lastRunSeconds !== null && lastRunSeconds < 90, measured: lastRunSeconds !== null, sub: lastRunSeconds === null ? 'Shown after the next analysis' : 'Last run, start to ranked themes' },
    { label: 'Revenue at risk', value: metrics ? `$${Math.round(metrics.total_revenue_at_risk / 1000).toLocaleString('en-US')}k` : '—', target: '', met: false, measured: Boolean(metrics), sub: `Across ${plural(metrics?.total_themes_discovered ?? 0, 'theme')}, each account once` },
  ];

  const demoView = <>
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.01em] text-ink">Demo benchmark</h1>
        <p className="mt-1 max-w-[68ch] text-muted">300 synthetic app reviews, support emails and a sales call, each labelled with its true theme, so the numbers below are measured rather than estimated. Anyone signed in can look; nothing here can be changed.</p>
      </div>
      <button onClick={runDemoAnalysis} disabled={working === 'pipeline'} className="btn-primary shrink-0">{working === 'pipeline' && <LoaderCircle size={14} className="animate-spin"/>} Analyze feedback</button>
    </div>
    <div className="mt-6">
      {noticeBanner}
      {!apiOnline && <p className="mb-5 rounded-md border-l-[3px] border-caution bg-caution-soft px-4 py-3 text-[13px] text-caution">{API_HINT}</p>}
      {apiOnline && metrics && metrics.total_feedback_items === 0 && <p className="mb-5 rounded-md border-l-[3px] border-caution bg-caution-soft px-4 py-3 text-[13px] text-caution">The demo data is not loaded. Run <code>python seed.py</code> in the project folder, then click Analyze feedback.</p>}
      <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-5">
        {metricCells.map((cell) => (
          <div key={cell.label} className="bg-surface px-4 py-3.5">
            <dt className="text-[13px] text-muted">{cell.label}</dt>
            <dd className="tnum mt-1 text-[24px] font-semibold leading-tight text-ink">{cell.value}</dd>
            {cell.target && <dd className={`text-[12px] font-medium ${!cell.measured ? 'text-muted' : cell.met ? 'text-link' : 'text-caution'}`}>Target {cell.target}{cell.measured ? (cell.met ? ', met' : ', not yet') : ''}</dd>}
            <dd className="text-[12px] leading-snug text-muted">{cell.sub}</dd>
          </div>
        ))}
      </dl>
      {metrics && metrics.top_3_breakdown.length > 0 && (
        <section className="panel mt-5 px-5 py-4 sm:px-7">
          <h2 className="text-[15px] font-semibold text-ink">How theme precision was scored</h2>
          <p className="text-[13px] text-muted">The true top 3 by revenue at risk: {metrics.ground_truth_top_3.map((label) => label.replaceAll('_', ' ')).join(', ')}.</p>
          <ol className="mt-3">{metrics.top_3_breakdown.map((row, index) => (
            <li key={index} className={`flex items-center gap-3 py-2 text-[13px] ${index ? 'border-t border-rule' : ''}`}>
              <span className="tnum w-5 text-faint">{index + 1}</span>
              <span className="min-w-0 flex-1 truncate text-ink">{row.title}</span>
              <span className="hidden text-muted sm:inline">{row.matched_ground_truth_theme ? `${row.matched_ground_truth_theme.replaceAll('_', ' ')}, ${row.purity}% pure` : 'no label'}</span>
              {row.is_in_ground_truth_top_3 ? <span className="font-medium text-link">hit</span> : <span className="font-medium text-caution">miss</span>}
            </li>
          ))}</ol>
        </section>
      )}
      <h2 className="mb-3 mt-8 text-[17px] font-semibold text-ink">Themes to review</h2>
      {roadmapPanel}
      {(approvedThemes.length > 0 || rejectedCount > 0) && <><h2 className="mb-3 mt-8 text-[17px] font-semibold text-ink">Approved</h2>{approvedPanel}</>}
    </div>
  </>;

  if (!ready) return <div className="flex min-h-screen items-center justify-center bg-paper"><LoaderCircle className="animate-spin text-muted" size={22} aria-label="Loading"/></div>;

  const tabs = [
    { key: 'roadmap' as const, label: 'Roadmap', count: pendingThemes.length },
    { key: 'sources' as const, label: 'Sources', count: sources.length },
    { key: 'approved' as const, label: 'Approved', count: approvedThemes.length },
  ];
  const navItem = (selected: boolean) => `flex w-full shrink-0 items-center gap-2 rounded-md px-2.5 py-2 text-left text-[14px] transition-colors md:w-full ${selected ? 'bg-chrome-active font-medium text-on-chrome shadow-[inset_3px_0_0_var(--color-brand)]' : 'text-on-chrome-muted hover:bg-chrome-active hover:text-on-chrome'}`;

  return <div className="min-h-screen bg-paper text-ink">
    <header className="sticky top-0 z-30 border-b border-chrome-rule bg-chrome text-on-chrome">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-3 px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <span className="text-[20px] font-bold tracking-[-0.02em] text-brand">motif</span>
          {!apiOnline && <span className="truncate rounded bg-caution-soft px-2 py-0.5 text-[12px] font-medium text-caution">Not connected to the API</span>}
        </div>
        <div className="flex items-center gap-1">
          <div className="mr-3 hidden sm:block"><ThemePicker/></div>
          {userEmail && <span className="mr-2 hidden max-w-[220px] truncate text-[13px] text-on-chrome-muted md:inline" title={userEmail}>{userEmail}</span>}
          <button onClick={refresh} className="btn-chrome" title="Load the latest themes"><RefreshCw size={14}/><span className="hidden sm:inline">Refresh</span></button>
          {authEnabled && <button onClick={signOut} className="btn-chrome">Sign out</button>}
        </div>
      </div>
    </header>

    <div className="mx-auto grid max-w-[1440px] grid-cols-1 md:min-h-[calc(100vh-57px)] md:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="border-b border-chrome-rule bg-chrome text-on-chrome md:border-b-0 md:border-r">
        <div className="px-3 py-3 md:py-5">
          <div className="mb-1.5 flex items-center justify-between px-2.5">
            <h2 className="text-[13px] font-semibold text-on-chrome">Projects</h2>
            <button onClick={() => { setShowCreate(true); setError(''); }} className="btn-chrome -mr-2 px-1.5 py-1"><Plus size={14}/> New</button>
          </div>
          <div className="flex gap-1 overflow-x-auto md:flex-col">
            {projects.length ? projects.map((project) => (
              <button key={project.id} onClick={() => { setActiveId(project.id); setError(''); }} className={`${navItem(!isDemo && activeProject?.id === project.id)} max-w-[70vw] md:max-w-none`}>
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
                {project.role && project.role !== 'owner' && <span className="shrink-0 text-[12px] text-on-chrome-muted">{project.role === 'viewer' ? 'view only' : 'shared'}</span>}
              </button>
            )) : <p className="px-2.5 py-1 text-[13px] text-on-chrome-muted">No projects yet.</p>}
          </div>
          <div className="mt-3 flex items-center justify-between px-2.5 sm:hidden"><span className="text-[13px] text-on-chrome-muted">Theme</span><ThemePicker/></div>
          <h2 className="mb-1.5 mt-4 hidden px-2.5 text-[13px] font-semibold text-on-chrome md:mt-7 md:block">Example data</h2>
          <button onClick={() => { setActiveId(DEMO_ID); setError(''); }} className={`${navItem(isDemo)} mt-1 md:mt-0`}>
            <span className="min-w-0 flex-1 truncate">Demo benchmark</span><span className="tnum shrink-0 text-[12px] text-on-chrome-muted">300</span>
          </button>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 md:px-10 md:py-9">
        <div className="mx-auto max-w-[1128px]">
          {isDemo ? demoView : !activeProject ? (
            <div className="max-w-[60ch] py-16">
              <h1 className="text-[28px] font-semibold leading-tight text-ink">Create your first project</h1>
              <p className="mt-2 text-muted">A project holds the feedback for one product: call notes, research docs, support exports. Motif groups it into themes, ranks them, and backs each one with your customers&apos; own words.</p>
              <button onClick={() => setShowCreate(true)} className="btn-primary mt-6"><Plus size={14}/> New project</button>
              <p className="mt-4 text-[13px] text-muted">Or look around the <button onClick={() => setActiveId(DEMO_ID)} className="font-medium text-link underline-offset-2 hover:underline">demo benchmark</button> first.</p>
            </div>
          ) : <>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.01em] text-ink">{activeProject.name}</h1>
                <p className="mt-1 text-muted">
                  {plural(sources.length, 'source')}, {plural(pendingThemes.length, 'theme')} to review, {approvedThemes.length} approved. Ranked for{' '}
                  <select value={rankingProfile} onChange={(event) => setRankingProfile(event.target.value as 'b2b_saas' | 'dev_tools')} disabled={working === 'pipeline' || !canEdit} aria-label="Rank for" className="cursor-pointer rounded border-0 border-b border-dashed border-muted bg-transparent px-0.5 font-medium text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-action/30">
                    <option value="b2b_saas">B2B SaaS</option>
                    <option value="dev_tools">developer tools</option>
                  </select>{' '}on the next analysis.
                </p>
                {!isOwner && <p className="mt-2 flex items-center gap-1.5 text-[13px] text-muted" data-testid="shared-banner"><Users size={14} className="shrink-0"/>Shared with you by {activeProject.ownerEmail || 'the owner'}. {canEdit ? 'You can add sources, analyze, approve and reject; the owner manages people and connected tools.' : 'You have view-only access: you can read themes and their evidence.'}</p>}
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {authEnabled && <button onClick={() => setShowShare(true)} className="btn"><Users size={14}/> {isOwner ? 'Share' : 'Members'}</button>}
                <button onClick={runAnalysis} disabled={working === 'pipeline' || !sources.length || !canEdit} title={sources.length ? undefined : 'Add a source first'} className="btn-primary">{working === 'pipeline' && <LoaderCircle size={14} className="animate-spin"/>} Analyze feedback</button>
              </div>
            </div>

            <div className="mt-6 flex gap-6 overflow-x-auto border-b border-rule" role="tablist" aria-label="Project sections">
              {tabs.map((item) => (
                <button key={item.key} role="tab" aria-selected={tab === item.key} onClick={() => setTab(item.key)} className={`-mb-px shrink-0 border-b-[3px] pb-2.5 text-[14px] font-medium transition-colors ${tab === item.key ? 'border-action text-ink' : 'border-transparent text-muted hover:text-ink'}`}>
                  {item.label} <span className="tnum font-normal text-muted">{item.count}</span>
                </button>
              ))}
            </div>

            <div className="mt-5">
              {noticeBanner}
              {tab === 'roadmap' ? roadmapPanel : tab === 'sources' ? sourcesPanel : approvedPanel}
            </div>
          </>}
        </div>
      </main>
    </div>

    {showShare && activeProject && <ShareProject projectId={activeProject.id} projectName={activeProject.name} myEmail={userEmail} onClose={() => setShowShare(false)} onLeft={() => { const name = activeProject.name; setShowShare(false); setProjects((current) => current.filter((project) => project.id !== activeProject.id)); setActiveId(''); setNotice(`You left “${name}”.`); }}/>}

    {showCreate && (
      <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="New project">
        <form onSubmit={createProject} className="modal-card">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-[18px] font-semibold text-ink">New project</h2>
              <p className="mt-1 text-[13px] text-muted">One project per product or area you collect feedback for.</p>
            </div>
            <button type="button" onClick={() => setShowCreate(false)} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>
          </div>
          <label className="mt-5 block text-[13px] font-medium text-ink">Name<input autoFocus value={newName} onChange={(event) => setNewName(event.target.value)} className="field mt-1.5 w-full" placeholder="Billing and invoices" required/></label>
          <label className="mt-4 block text-[13px] font-medium text-ink">GitHub repository <span className="font-normal text-muted">(optional)</span><input value={newRepo} onChange={(event) => setNewRepo(event.target.value)} className="field mt-1.5 w-full" placeholder="owner/repo"/></label>
          <p className="mt-2 text-[12px] text-muted">Approved themes become issues here. Leave it empty to use the server&apos;s default repository.</p>
          <div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setShowCreate(false)} className="btn-text">Cancel</button><button className="btn-primary">Create project</button></div>
        </form>
      </div>
    )}

    {reviewTheme && (
      <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Theme evidence">
        <div className="modal-card max-h-[88vh] max-w-2xl overflow-y-auto">
          <div className="flex items-start justify-between gap-3">
            <p className="text-[13px] text-muted">{reviewTheme.score_breakdown ? `Ranked ${reviewTheme.score_breakdown.rank} of ${reviewTheme.score_breakdown.of}` : 'Theme'}</p>
            <button onClick={() => setReviewTheme(null)} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>
          </div>
          <label className="mt-1 block text-[13px] font-medium text-muted">Title<input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} disabled={!canEdit || demoLocked} className="field mt-1 w-full text-[16px] font-semibold"/></label>
          <label className="mt-3 block text-[13px] font-medium text-muted">Problem<textarea value={editSummary} onChange={(event) => setEditSummary(event.target.value)} disabled={!canEdit || demoLocked} rows={3} className="field mt-1 w-full resize-y leading-relaxed"/></label>
          {(editTitle.trim() !== reviewTheme.title || editSummary.trim() !== reviewTheme.summary) && <p className="mt-2 text-[12px] text-caution">Edited. Approving now records it as approved with edits.</p>}
          {!canEdit && <p className="mt-3 text-[13px] text-muted">You have view-only access, so you can read the evidence but not approve or reject.</p>}

          {reviewTheme.score_breakdown?.issue_type && (
            <section className="mt-5 rounded-md bg-paper px-4 py-3" aria-label="Kind of problem">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label htmlFor="issue-type" className="text-[13px] font-semibold text-ink">Kind of problem</label>
                <select id="issue-type" value={reviewTheme.score_breakdown.issue_type.type} disabled={!canEdit || demoLocked || working === `type:${reviewTheme.id}`} onChange={(event) => retypeTheme(reviewTheme, event.target.value)} className="field py-1.5 text-[13px]">
                  <option value="security">Security (fixed first)</option>
                  <option value="bug">Bug</option>
                  <option value="ux">UX friction</option>
                  <option value="feature">Feature request</option>
                  <option value="general">General</option>
                </select>
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{typeReason(reviewTheme.score_breakdown.issue_type)} {reviewTheme.score_breakdown.issue_type.why}</p>
              {canEdit && !demoLocked && <p className="mt-1 text-[12px] text-muted">Changing it re-weights this theme and re-ranks the project. It is recorded in the history.</p>}
            </section>
          )}

          <h3 className="mt-6 text-[15px] font-semibold text-ink">What customers said</h3>
          {reviewTheme.cited_quotes?.length ? (
            <ul className="mt-2">{reviewTheme.cited_quotes.map((quote, index) => (
              <li key={index} className={`py-3 ${index ? 'border-t border-rule' : ''}`}>
                <blockquote className="quote">“<span className="marked">{quote.quote_text}</span>”</blockquote>
                <p className="mt-1 text-[13px] text-muted">{[quote.customer_id, quote.customer_id && quote.customer_tier && quote.customer_tier !== 'free' ? `${quote.customer_tier} plan` : null, quote.source_name].filter(Boolean).join(', ') || 'From your sources'}</p>
              </li>
            ))}</ul>
          ) : <p className="mt-2 text-muted">No verified quotes for this theme.</p>}

          <ScoreProof breakdown={reviewTheme.score_breakdown}/>

          {reviewTheme.activity?.length ? <>
            <h3 className="mt-6 text-[15px] font-semibold text-ink">History</h3>
            <ul className="mt-1 text-[13px] text-muted" aria-label="History">{reviewTheme.activity.map((item, index) => <li key={index} className="py-0.5">{describeActivity(item)}</li>)}</ul>
          </> : null}

          <div className="sticky -bottom-6 -mx-6 -mb-6 mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-rule bg-surface px-6 py-4">
            <button onClick={() => setReviewTheme(null)} className="btn-text mr-auto">Close</button>
            {demoLocked ? <button onClick={() => launchTheme(reviewTheme)} disabled={Boolean(working)} className="btn-primary">{working === reviewTheme.id && <LoaderCircle size={14} className="animate-spin"/>} Preview PRD</button> : <>
              <button onClick={() => dismissTheme(reviewTheme)} disabled={Boolean(working) || !canEdit} className="btn-danger">Reject</button>
              <button onClick={() => launchTheme(reviewTheme, { title: editTitle, summary: editSummary })} disabled={Boolean(working) || !editTitle.trim() || !canEdit} title="Writes the PRD and opens a GitHub issue" className="btn-primary">{working === reviewTheme.id ? <LoaderCircle size={14} className="animate-spin"/> : <Check size={14}/>} Approve</button>
            </>}
          </div>
        </div>
      </div>
    )}

    {prdTheme && (
      <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="PRD">
        <div className="modal-card max-h-[88vh] max-w-2xl overflow-y-auto">
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-[13px] text-muted">PRD</p><h2 className="mt-0.5 text-[18px] font-semibold text-ink">{prdTheme.title}</h2></div>
            <button onClick={() => setPrdTheme(null)} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>
          </div>
          {prdTheme.github_issue_url
            ? <a href={prdTheme.github_issue_url} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 font-medium text-link hover:underline">Issue #{prdTheme.github_issue_number} is open in GitHub <ExternalLink size={13}/></a>
            : <p className="mt-4 rounded-md border-l-[3px] border-caution bg-caution-soft px-4 py-3 text-[13px] text-caution">Not sent to GitHub. To open real issues, set GITHUB_TOKEN, GITHUB_REPO_OWNER and GITHUB_REPO_NAME in the backend .env file.</p>}
          <pre className="mt-4 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-md bg-paper p-4 font-mono text-[12.5px] leading-relaxed text-ink">{prdTheme.prd_markdown || 'No PRD text came back for this theme.'}</pre>
          <div className="mt-5 flex justify-end gap-2">
            {prdTheme.prd_markdown && <button onClick={() => copyPrd(prdTheme.prd_markdown || '')} className="btn"><Clipboard size={14}/>{copied ? 'Copied' : 'Copy PRD'}</button>}
            <button onClick={() => setPrdTheme(null)} className="btn-primary">Done</button>
          </div>
        </div>
      </div>
    )}
  </div>;
}
