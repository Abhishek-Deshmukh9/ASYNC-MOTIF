'use client';

import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowDown, ExternalLink, FolderOpen, Inbox, LoaderCircle, Mic, MicOff, Plus, RefreshCw, Search, Trash2, Upload, Users, X,
} from 'lucide-react';
import { SIGN_IN_REQUIRED, approveTheme, deleteSource, fetchMetrics, fetchProjects, fetchPipelineStatus, fetchSources, fetchThemes, ingestSource, rejectTheme, runPipeline, saveProject, uploadSources } from '@/utils/api';
import { authEnabled, getSupabase } from '@/utils/supabase';
import type { PipelineProgress } from '@/utils/api';
import Connectors from '@/components/Connectors';
import ShareProject from '@/components/ShareProject';
import EvidencePanel from '@/components/EvidencePanel';
import MetricStrip from '@/components/MetricStrip';
import PipelineProgressBar from '@/components/PipelineProgress';
import PrdDialog from '@/components/PrdDialog';
import ThemeCard from '@/components/ThemeCard';
import { RankingKey } from '@/components/ScoreBreakdown';
import type { EvalMetrics, Project, ProjectSource, Theme, ThemeActivity, UploadFileResult, UploadedSource } from '@/utils/types';

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
const pct = (value: number | null | undefined) => (value === null || value === undefined ? 'Ã¢â‚¬â€' : `${value}%`);
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
  const verb = item.action === 'approved' && item.changed_title ? 'Approved with edits' : item.action.charAt(0).toUpperCase() + item.action.slice(1);
  return `${verb} by ${item.by}${item.at ? `, ${since(item.at)}` : ''}`;
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
  const [prdTheme, setPrdTheme] = useState<Theme | null>(null);
  const [progress, setProgress] = useState<PipelineProgress | null>(null);
  const [lastRunSeconds, setLastRunSeconds] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
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
    setNotice(`Created Ã¢â‚¬Å“${name}Ã¢â‚¬Â. Add sources, then analyze them.`); setTab('sources');
    setError('');
  };

  const saveSource = async (source: ProjectSource, sync = true) => {
    if (!activeProject) return;
    updateProject(activeProject.id, (project) => ({ ...project, sources: [source, ...project.sources] }));
    setNotice(`Saved Ã¢â‚¬Å“${source.name}Ã¢â‚¬Â to ${activeProject.name}.`);
    setError('');
    if (sync && apiOnline) {
      try {
        const serverId = await ingestSource(source, activeProject.id, activeProject.name);
        updateProject(activeProject.id, (project) => ({ ...project, sources: project.sources.map((item) => item.id === source.id ? { ...item, syncState: 'synced', serverId: serverId ?? undefined } : item) }));
        setNotice(`Saved Ã¢â‚¬Å“${source.name}Ã¢â‚¬Â to ${activeProject.name} and synced it to Motif.`);
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

    setWorking('upload'); setError(''); setNotice(`Reading ${plural(usable.length, 'file')}Ã¢â‚¬Â¦`);
    const results: UploadFileResult[] = [];
    try {
      for (const [index, files] of batches.entries()) {
        if (batches.length > 1) setNotice(`Reading filesÃ¢â‚¬Â¦ batch ${index + 1} of ${batches.length}`);
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
      setNotice(`Removed Ã¢â‚¬Å“${source.name}Ã¢â‚¬Â. Analyze again to update the themes.`);
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
        const audioLink = document.createElement('a'); audioLink.href = audioUrl; audioLink.download = `${meetingName.trim() || 'Meeting'} Ã¢â‚¬â€ audio.webm`; audioLink.click(); URL.revokeObjectURL(audioUrl);
      }
    }
    const text = transcriptRef.current.trim();
    if (!text) { setError('No speech was captured. Check the microphone and try again.'); return; }
    const filename = `${meetingName.trim() || 'Meeting transcript'} Ã¢â‚¬â€ ${new Date().toLocaleDateString()}.md`;
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
    setReviewTheme(theme);
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

  const dismissTheme = async (theme: Theme) => {
    setWorking(theme.id); setError('');
    try {
      await rejectTheme(theme.id);
      setThemes((existing) => existing.map((item) => item.id === theme.id ? { ...item, status: 'rejected' } : item));
      setReviewTheme(null);
      setNotice(`Rejected Ã¢â‚¬Å“${theme.title}Ã¢â‚¬Â. It stays in the history.`);
      if (isDemo) fetchMetrics().then(setMetrics).catch(() => undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reject this theme.');
      if (cause instanceof Error && cause.message.startsWith('Already')) { setReviewTheme(null); fetchThemes(isDemo ? undefined : activeProject?.id).then(setThemes).catch(() => undefined); }
    }
    finally { setWorking(''); }
  };


  // Drag-and-drop handlers for file upload
  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const onDragLeave = () => setIsDragging(false);
  const onDrop = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false); importFiles(Array.from(e.dataTransfer.files)); };


  const noticeBanner = (<>
    <PipelineProgressBar progress={progress} working={working}/>
    {(notice || error) ? (
      <div role={error ? 'alert' : 'status'} className={`mb-5 flex items-start justify-between gap-3 rounded-md border-l-[3px] px-4 py-3 text-[13px] leading-relaxed ${error ? 'border-danger bg-danger-soft text-danger' : 'border-action bg-action-soft text-ink'}`}>
        <p>{error || notice}</p>
        <button onClick={() => { setNotice(''); setError(''); }} aria-label="Dismiss" className="icon-btn -my-1 -mr-2 h-7 w-7"><X size={14}/></button>
      </div>
    ) : null}
  </>);

  const downloadSource = (source: ProjectSource) => {
    const blob = new Blob([source.content], { type: 'text/markdown' }); const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = source.name; link.click(); URL.revokeObjectURL(url);
  };

  const roadmapPanel = (
    <section className="panel overflow-hidden" aria-label="Themes to review">
      <RankingKey breakdown={pendingThemes.find((t) => t.score_breakdown)?.score_breakdown}/>
      {pendingThemes.length ? <ol>{pendingThemes.map((theme, index) => (
        <ThemeCard key={theme.id} theme={theme} index={index} working={working} canEdit={canEdit} demoLocked={demoLocked} onApprove={launchTheme} onReject={dismissTheme} onOpenEvidence={openReview}/>
      ))}</ol> : (
        <div className="px-5 py-12 text-center sm:px-7">
          <Inbox size={32} className="mx-auto text-faint"/>
          <p className="mt-3 font-medium text-ink">{themes.length ? 'Nothing left to review' : 'No themes yet'}</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-muted">{themes.length ? 'Every theme has a decision. Approved ones are listed under Approved.' : isDemo ? 'Click Analyze feedback to group the demo data into themes.' : 'Add sources, then click Analyze feedback. A theme needs at least four passages about the same problem.'}</p>
          {!themes.length && !isDemo && <button onClick={() => setTab('sources')} className="btn mt-4">Add sources</button>}
        </div>
      )}
    </section>
  );


  const approvedPanel = (
    <section className="panel overflow-hidden" aria-label="Approved themes">
      {approvedThemes.length ? <ul>{approvedThemes.map((theme, index) => {
        const decided = theme.activity?.find((item) => item.action === 'approved');
        return (
          <li key={theme.id} className={`flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:px-7 ${index ? 'border-t border-rule' : ''}`}>
            <div className="min-w-0 flex-1">
              <p className="font-medium text-ink">{theme.title}</p>
              <p className="text-[13px] text-muted">
                {theme.github_issue_url ? <a href={theme.github_issue_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-action hover:underline">Issue #{theme.github_issue_number} <ExternalLink size={12}/></a> : 'PRD written, no GitHub issue'}
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
    <div className="space-y-5" onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
      {isDragging && <div className="flex items-center justify-center rounded-lg border-2 border-dashed border-action bg-action-soft px-6 py-10 text-[14px] font-medium text-action"><Upload size={18} className="mr-2"/> Drop files here to import</div>}
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
      <MetricStrip metrics={metrics} lastRunSeconds={lastRunSeconds} isDemo={true}/>
      {metrics && metrics.top_3_breakdown.length > 0 && (
        <section className="panel mt-5 px-5 py-4 sm:px-7">
          <h2 className="text-[15px] font-semibold text-ink">How theme precision was scored</h2>
          <p className="text-[13px] text-muted">The true top 3 by revenue at risk: {metrics.ground_truth_top_3.map((label) => label.replaceAll('_', ' ')).join(', ')}.</p>
          <ol className="mt-3">{metrics.top_3_breakdown.map((row, index) => (
            <li key={index} className={`flex items-center gap-3 py-2 text-[13px] ${index ? 'border-t border-rule' : ''}`}>
              <span className="tnum w-5 text-faint">{index + 1}</span>
              <span className="min-w-0 flex-1 truncate text-ink">{row.title}</span>
              <span className="hidden text-muted sm:inline">{row.matched_ground_truth_theme ? `${row.matched_ground_truth_theme.replaceAll('_', ' ')}, ${row.purity}% pure` : 'no label'}</span>
              {row.is_in_ground_truth_top_3 ? <span className="font-medium text-action">hit</span> : <span className="font-medium text-caution">miss</span>}
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
  const navItem = (selected: boolean) => `flex w-full shrink-0 items-center gap-2 rounded-md px-2.5 py-2 text-left text-[14px] transition-colors md:w-full ${selected ? 'bg-paper font-medium text-ink shadow-[inset_2px_0_0_var(--color-action)]' : 'text-muted hover:bg-paper hover:text-ink'}`;

  return <div className="min-h-screen bg-paper text-ink">
    <header className="sticky top-0 z-30 border-b border-rule bg-surface">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-3 px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <span className="text-[20px] font-bold tracking-[-0.02em] text-ink"><span className="marked">motif</span></span>
          <span className={`h-2 w-2 shrink-0 rounded-full ${apiOnline ? 'bg-action' : 'bg-caution'}`} title={apiOnline ? 'API connected' : 'Not connected to the API'}/>
          {activeProject && !isDemo && <span className="hidden truncate text-[13px] font-medium text-ink md:inline">{activeProject.name}</span>}
        </div>
        <div className="flex items-center gap-1">
          {userEmail && <span className="mr-2 hidden max-w-[220px] truncate text-[13px] text-muted md:inline" title={userEmail}>{userEmail}</span>}
          <button onClick={refresh} className="btn-text" title="Load the latest themes"><RefreshCw size={14}/><span className="hidden sm:inline">Refresh</span></button>
          {authEnabled && <button onClick={signOut} className="btn-text">Sign out</button>}
        </div>
      </div>
    </header>

    <div className="mx-auto grid max-w-[1440px] grid-cols-1 md:min-h-[calc(100vh-57px)] md:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="border-b border-rule bg-surface md:border-b-0 md:border-r">
        <div className="px-3 py-3 md:py-5">
          <div className="mb-1.5 flex items-center justify-between px-2.5">
            <h2 className="text-[13px] font-semibold text-ink">Projects</h2>
            <button onClick={() => { setShowCreate(true); setError(''); }} className="btn-text -mr-2 px-1.5 py-1"><Plus size={14}/> New</button>
          </div>
          <div className="flex gap-1 overflow-x-auto md:flex-col">
            {projects.length ? projects.map((project) => (
              <button key={project.id} onClick={() => { setActiveId(project.id); setError(''); }} className={`${navItem(!isDemo && activeProject?.id === project.id)} max-w-[70vw] md:max-w-none`}>
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
                {project.role && project.role !== 'owner' && <span className="shrink-0 text-[12px] text-muted">{project.role === 'viewer' ? 'view only' : 'shared'}</span>}
              </button>
            )) : <p className="px-2.5 py-1 text-[13px] text-muted">No projects yet.</p>}
          </div>
          <h2 className="mb-1.5 mt-4 hidden px-2.5 text-[13px] font-semibold text-ink md:mt-7 md:block">Example data</h2>
          <button onClick={() => { setActiveId(DEMO_ID); setError(''); }} className={`${navItem(isDemo)} mt-1 md:mt-0`}>
            <span className="min-w-0 flex-1 truncate">Demo benchmark</span><span className="tnum shrink-0 text-[12px] text-muted">300</span>
          </button>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 md:px-10 md:py-9">
        <div className="mx-auto max-w-[1040px]">
          {isDemo ? demoView : !activeProject ? (
            <div className="max-w-[60ch] py-16">
              <h1 className="text-[28px] font-semibold leading-tight text-ink">Create your first project</h1>
              <p className="mt-2 text-muted">A project holds the feedback for one product: call notes, research docs, support exports. Motif groups it into themes, ranks them, and backs each one with your customers&apos; own words.</p>
              <button onClick={() => setShowCreate(true)} className="btn-primary mt-6"><Plus size={14}/> New project</button>
              <p className="mt-4 text-[13px] text-muted">Or look around the <button onClick={() => setActiveId(DEMO_ID)} className="font-medium text-action underline-offset-2 hover:underline">demo benchmark</button> first.</p>
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
                <button key={item.key} role="tab" aria-selected={tab === item.key} onClick={() => setTab(item.key)} className={`-mb-px shrink-0 border-b-2 pb-2.5 text-[14px] font-medium transition-colors ${tab === item.key ? 'border-action text-ink' : 'border-transparent text-muted hover:text-ink'}`}>
                  {item.label} <span className="tnum font-normal text-muted">{item.count}</span>
                </button>
              ))}
            </div>

            <div className="mt-5">
              {noticeBanner}
              {tab === 'roadmap' && <div className="mb-5"><MetricStrip metrics={metrics} lastRunSeconds={lastRunSeconds} isDemo={false}/></div>}
              {tab === 'roadmap' ? roadmapPanel : tab === 'sources' ? sourcesPanel : approvedPanel}
            </div>
          </>}
        </div>
      </main>
    </div>

    {showShare && activeProject && <ShareProject projectId={activeProject.id} projectName={activeProject.name} myEmail={userEmail} onClose={() => setShowShare(false)} onLeft={() => { const name = activeProject.name; setShowShare(false); setProjects((current) => current.filter((project) => project.id !== activeProject.id)); setActiveId(''); setNotice(`You left Ã¢â‚¬Å“${name}Ã¢â‚¬Â.`); }}/>}

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

    <EvidencePanel theme={reviewTheme} canEdit={canEdit} demoLocked={demoLocked} working={working} onClose={() => setReviewTheme(null)} onApprove={(t, edits) => launchTheme(t, edits)} onReject={dismissTheme}/>
    <PrdDialog theme={prdTheme} onClose={() => setPrdTheme(null)}/>
  </div>;
}
