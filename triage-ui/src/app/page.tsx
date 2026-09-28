'use client';

import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowDown, ArrowRight, AudioLines, Check, CheckCircle2,
  CircleHelp, Cloud, FileText, FolderKanban, GitBranch, HardDrive, Headphones,
  LoaderCircle, Mic, MicOff, Plus, Radio, RefreshCw, Search, Sparkles,
  Upload, X, Zap,
} from 'lucide-react';
import { approveTheme, fetchThemes, ingestSource, runPipeline } from '@/utils/api';
import type { Project, ProjectSource, Theme } from '@/utils/types';

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
  const fileInput = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<BrowserRecognition | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunks = useRef<Blob[]>([]);
  const transcriptRef = useRef('');

  const activeProject = projects.find((project) => project.id === activeId) || projects[0];
  const sources = activeProject?.sources || [];
  const filteredSources = sources.filter((source) => source.name.toLowerCase().includes(sourceSearch.toLowerCase()));
  const pendingThemes = useMemo(() => themes.filter((theme) => theme.status === 'pending_review'), [themes]);

  useEffect(() => {
    // Browser storage is intentionally read after hydration to avoid SSR/client mismatch.
    const loaded = readProjects();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProjects(loaded);
    setActiveId(loaded[0]?.id || '');
    setReady(true);
  }, []);

  useEffect(() => {
    if (!activeId) return;
    fetchThemes(activeId).then((value) => { setThemes(value); setApiOnline(true); }).catch(() => setApiOnline(false));
  }, [activeId]);

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
        await ingestSource(source, activeProject.id);
        updateProject(activeProject.id, (project) => ({ ...project, sources: project.sources.map((item) => item.id === source.id ? { ...item, syncState: 'synced' } : item) }));
        setNotice(`Saved “${source.name}” to ${activeProject.name} and synced it to Motif.`);
      } catch { setError('Saved in this browser, but could not sync to the backend. Check that the API and database are running.'); }
    }
  };

  const onFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!activeProject || !files.length) return;
    for (const file of files) {
      const text = await file.text();
      if (!text.trim()) continue;
      const source: ProjectSource = { id: makeId(), name: file.name, kind: 'document', createdAt: new Date().toISOString(), content: text.slice(0, 120_000), syncState: 'local' };
      await saveSource(source);
    }
    event.target.value = '';
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
        await ingestSource(source, activeProject.id);
        updateProject(activeProject.id, (project) => ({ ...project, sources: project.sources.map((item) => item.id === source.id ? { ...item, syncState: 'synced' } : item) }));
      }
      const result = await runPipeline(activeProject.id);
      const updated = await fetchThemes(activeProject.id); setThemes(updated); setApiOnline(true);
      setNotice(`Analysis complete. ${result.themes_created ?? updated.length} themes are ready for your review.`);
    } catch (cause) { setApiOnline(false); setError(cause instanceof Error ? cause.message : API_HINT); }
    finally { setWorking(''); }
  };

  const launchTheme = async (theme: Theme) => {
    setWorking(theme.id); setError('');
    try {
      const result = await approveTheme(theme.id, theme.title, activeProject?.repo);
      setThemes((existing) => existing.map((item) => item.id === theme.id ? { ...item, status: 'approved', github_issue_url: result.github_issue_url, github_issue_number: result.github_issue_number, prd_markdown: result.prd_markdown } : item));
      setReviewTheme(null);
      setNotice(result.github_issue_url ? `Issue #${result.github_issue_number} created in GitHub.` : 'Theme approved. Configure GitHub on the backend to dispatch the issue.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not create GitHub issue. Check the GitHub configuration.'); }
    finally { setWorking(''); }
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
          <button onClick={() => { fetchThemes(activeProject?.id).then((value) => { setThemes(value); setApiOnline(true); }).catch(() => setApiOnline(false)); }} className="icon-btn" title="Refresh"><RefreshCw size={15}/></button>
          <button onClick={() => { setShowCreate(true); setError(''); }} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3.5 py-2.5 text-xs font-semibold text-white transition hover:bg-[#115e59]"><Plus size={15}/> New project</button>
        </div>
      </div>
    </header>

    <div className="mx-auto grid max-w-[1440px] grid-cols-1 md:min-h-[calc(100vh-73px)] md:grid-cols-[242px_minmax(0,1fr)]">
      <aside className="border-b border-slate-200 px-4 py-5 md:border-b-0 md:border-r md:px-4">
        <div className="mb-3 flex items-center justify-between px-2"><span className="text-[10px] font-semibold uppercase tracking-[.19em] text-slate-500">Workspaces</span><button onClick={() => setShowCreate(true)} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"><Plus size={14}/></button></div>
        {projects.length ? <div className="space-y-1">{projects.map((project) => <button key={project.id} onClick={() => { setActiveId(project.id); setError(''); }} className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left text-[13px] transition ${activeProject?.id === project.id ? 'bg-slate-100 text-slate-900' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'}`}><FolderKanban size={15} className={activeProject?.id === project.id ? 'text-[#0f766e]' : 'text-slate-500'}/><span className="min-w-0 flex-1 truncate">{project.name}</span><span className="text-[10px] text-slate-400">{project.sources.length}</span></button>)}</div> : <div className="px-2.5 py-3 text-xs leading-5 text-slate-400">Your project spaces will show up here.</div>}
        <div className="my-5 h-px bg-slate-100" />
        <div className="space-y-1 px-1">
          <div className="flex items-center gap-2 px-2 py-2 text-[10px] font-semibold uppercase tracking-[.19em] text-slate-500">Project flow</div>
          {[['01', 'Bring feedback together'], ['02', 'Discover themes'], ['03', 'Review the roadmap'], ['04', 'Launch to GitHub']].map(([n, label], i) => <div key={n} className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-xs text-slate-500"><span className={`font-mono text-[10px] ${i === 0 ? 'text-[#0f766e]' : 'text-slate-300'}`}>{n}</span>{label}</div>)}
        </div>
        <div className="mt-8 rounded-xl border border-slate-200 bg-slate-50 p-3.5"><div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-slate-700"><CircleHelp size={14} className="text-[#0f766e]"/> Your data stays scoped</div><p className="text-[11px] leading-[1.65] text-slate-500">Each project keeps its own source list. Nothing is sent to GitHub without your approval.</p></div>
      </aside>

      <main className="min-w-0 px-5 py-7 md:px-9 md:py-9">
        {!activeProject ? <div className="mx-auto flex min-h-[70vh] max-w-xl flex-col items-center justify-center text-center">
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-[20px] border border-emerald-700/20 bg-emerald-50 text-[#0f766e]"><FolderKanban size={28}/></div>
          <p className="mb-3 text-[10px] font-semibold uppercase tracking-[.22em] text-[#0f766e]">A clearer path from feedback to shipped work</p>
          <h1 className="text-3xl font-semibold tracking-[-.04em] text-slate-900 sm:text-4xl">Start with a project.</h1>
          <p className="mt-3 max-w-md text-sm leading-6 text-slate-600">Bring calls, research docs, and customer feedback into one evidence-backed roadmap. Motif finds the patterns; your team decides what ships.</p>
          <button onClick={() => setShowCreate(true)} className="mt-7 flex items-center gap-2 rounded-lg bg-[#0f766e] px-4 py-3 text-sm font-semibold text-white hover:bg-[#115e59]"><Plus size={16}/> Create your first project</button>
          <div className="mt-10 grid w-full grid-cols-3 gap-3 text-left">{[['Collect', 'Calls and docs'], ['Connect', 'Emergent themes'], ['Ship', 'Human-approved issues']].map(([title, desc], i) => <div key={title} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><span className="font-mono text-[10px] text-slate-400">0{i+1}</span><p className="mt-3 text-xs font-medium text-slate-800">{title}</p><p className="mt-1 text-[10px] text-slate-500">{desc}</p></div>)}</div>
        </div> : <>
          <div className="mb-8 flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
            <div><div className="mb-3 flex items-center gap-2 text-[11px] text-slate-500"><span>Projects</span><span>/</span><span className="text-slate-700">{activeProject.name}</span></div><h1 className="text-[28px] font-semibold tracking-[-.045em] text-slate-900 sm:text-[34px]">{activeProject.name}<span className="ml-3 align-middle text-sm font-normal tracking-normal text-slate-400">workspace</span></h1><p className="mt-2 max-w-xl text-[13px] leading-5 text-slate-600">Bring the evidence together. Motif will map recurring needs into themes you can inspect, prioritize, and launch.</p></div>
            <div className="flex flex-wrap items-center gap-2"><button onClick={() => setShowDrive(true)} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100"><HardDrive size={14}/> Add Drive folder</button><button onClick={() => fileInput.current?.click()} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100"><Upload size={14}/> Upload docs</button><button onClick={runAnalysis} disabled={working === 'pipeline' || !sources.length} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3.5 py-2.5 text-xs font-semibold text-white transition hover:bg-[#115e59] disabled:cursor-not-allowed disabled:opacity-40">{working === 'pipeline' ? <LoaderCircle size={14} className="animate-spin"/> : <Sparkles size={14}/>} Analyze feedback</button></div>
            <input ref={fileInput} type="file" multiple accept=".txt,.md,.csv,.json,.html,.log" className="hidden" onChange={onFiles}/>
          </div>

          {(notice || error) && <div className={`mb-5 flex items-start justify-between gap-3 rounded-lg border px-3.5 py-3 text-xs leading-5 ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-900'}`}><div className="flex gap-2.5">{error ? <CircleHelp size={15} className="mt-0.5 shrink-0 text-rose-600"/> : <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-[#0f766e]"/>}{error || notice}</div><button onClick={() => { setNotice(''); setError(''); }} className="text-slate-500 hover:text-slate-900"><X size={14}/></button></div>}

          <section className="mb-7 grid grid-cols-1 gap-3 lg:grid-cols-[1.3fr_.7fr]">
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6">
              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"><div><div className="flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-50 text-rose-600"><AudioLines size={15}/></span><span className="text-sm font-semibold text-slate-900">Capture a customer conversation</span></div><p className="mt-2 max-w-md text-xs leading-5 text-slate-500">Record a meeting in your browser and create a transcript file right in this project.</p></div><span className={`inline-flex items-center gap-1.5 self-start rounded-full border px-2.5 py-1 text-[10px] ${recording ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-500'}`}><span className={`h-1.5 w-1.5 rounded-full ${recording ? 'animate-pulse bg-rose-600' : 'bg-slate-300'}`}/>{recording ? 'Recording live' : 'Browser microphone'}</span></div>
              <div className="mt-5 flex flex-col gap-2 sm:flex-row"><input value={meetingName} onChange={(event) => setMeetingName(event.target.value)} className="field flex-1" aria-label="Meeting name" placeholder="Give this conversation a name"/><button onClick={recording ? stopMeeting : startMeeting} className={`flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition ${recording ? 'bg-rose-600 text-white hover:bg-rose-700' : 'bg-[#0f766e] text-white hover:bg-[#115e59]'}`}>{recording ? <><MicOff size={14}/> Stop & save transcript</> : <><Mic size={14}/> Start recording</>}</button></div>
              {(transcribing || transcript) && <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3.5"><div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[.17em] text-slate-500"><Radio size={12} className={transcribing ? 'text-rose-600' : 'text-slate-500'}/>{transcribing ? 'Live transcript' : 'Transcript preview'}</div><p className="max-h-28 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700">{transcript || 'Listening… start speaking to see words here.'}</p></div>}
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6"><div className="flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-50 text-blue-700"><Cloud size={15}/></span><span className="text-sm font-semibold text-slate-900">Connect Google Drive</span></div><p className="mt-2 text-xs leading-5 text-slate-500">Choose a project folder to keep research docs and meeting notes in scope.</p><button onClick={() => setShowDrive(true)} className="mt-5 flex items-center gap-2 text-xs font-medium text-slate-700 hover:text-[#0f766e]">Choose a folder <ArrowRight size={14}/></button><p className="mt-3 text-[10px] leading-4 text-slate-400">{activeProject.driveFolder ? 'Folder scope recorded · connector setup still required' : 'Private-by-default: only the folder you choose should be read.'}</p></div>
          </section>

          <section className="mb-7 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_2px_8px_rgba(15,23,42,0.035)]">
            <div className="flex flex-col justify-between gap-3 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:px-6"><div><div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-slate-900">Project sources</h2><span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600">{sources.length}</span></div><p className="mt-1 text-[11px] text-slate-500">A project-scoped evidence library. Add notes or transcripts as files.</p></div><div className="relative"><Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/><input value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} className="field h-8 w-full pl-8 text-[11px] sm:w-48" placeholder="Find a source"/></div></div>
            {filteredSources.length ? <div className="divide-y divide-slate-100">{filteredSources.map((source) => <div key={source.id} className="flex items-center gap-3 px-5 py-3.5 sm:px-6"><span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${source.kind === 'meeting' ? 'bg-rose-50 text-rose-700' : source.kind === 'drive' ? 'bg-blue-50 text-blue-700' : 'bg-violet-50 text-violet-700'}`}>{source.kind === 'meeting' ? <Headphones size={15}/> : source.kind === 'drive' ? <HardDrive size={15}/> : <FileText size={15}/>}</span><div className="min-w-0 flex-1"><div className="truncate text-xs font-medium text-slate-800">{source.name}</div><div className="mt-1 text-[10px] text-slate-400">{source.kind === 'meeting' ? 'Meeting transcript' : source.kind === 'drive' ? 'Google Drive' : 'Document'} <span className="mx-1">·</span>{new Date(source.createdAt).toLocaleDateString()}</div></div><span className={`hidden rounded-full px-2 py-1 text-[9px] sm:inline-flex ${source.syncState === 'synced' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{source.syncState === 'synced' ? 'Synced' : 'Saved locally'}</span><button title="Download source file" onClick={() => downloadSource(source)} className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><ArrowDown size={14}/></button></div>)}</div> : <div className="flex flex-col items-center px-5 py-10 text-center"><div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-500"><FileText size={18}/></div><p className="text-xs font-medium text-slate-700">{sources.length ? 'No matching files' : 'No sources in this project yet'}</p><p className="mt-1 max-w-sm text-[11px] leading-5 text-slate-400">{sources.length ? 'Try a different search.' : 'Upload a document or record a conversation. Each source stays grouped under this project.'}</p>{!sources.length && <button onClick={() => fileInput.current?.click()} className="mt-4 flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-[11px] text-slate-700 hover:bg-slate-100"><Upload size={13}/> Add first document</button>}</div>}
          </section>

          <section className="mb-7 rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_8px_rgba(15,23,42,0.035)] sm:p-6">
            <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><div className="flex items-center gap-2"><Activity size={15} className="text-[#0f766e]"/><h2 className="text-sm font-semibold text-slate-900">Roadmap signal map</h2></div><p className="mt-1 text-[11px] text-slate-500">Sources → evidence → emergent themes → approved GitHub issue</p></div><button onClick={runAnalysis} disabled={working === 'pipeline' || !sources.length} className="flex items-center gap-2 self-start rounded-lg border border-slate-200 px-3 py-2 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"><Zap size={13}/>{working === 'pipeline' ? 'Analyzing…' : 'Build roadmap'}</button></div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_28px_1fr_28px_1fr_28px_1fr] sm:items-center">{[
              {label:'Feedback sources', count:sources.length, icon:<FileText size={15}/>, sub:'Project inputs', color:'text-slate-700'},
              {label:'Evidence library', count:sources.length, icon:<Search size={15}/>, sub:'Quotes & signals', color:'text-blue-700'},
              {label:'Discovered themes', count:themes.length, icon:<Sparkles size={15}/>, sub:pendingThemes.length ? `${pendingThemes.length} awaiting review` : 'HDBSCAN clusters', color:'text-violet-700'},
              {label:'GitHub issues', count:themes.filter((theme) => theme.github_issue_url).length, icon:<GitBranch size={15}/>, sub:'Human approved', color:'text-[#0f766e]'},
            ].map((step, index) => <div key={step.label} className="contents"><div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5"><div className={`mb-3 flex items-center gap-2 text-[10px] ${step.color}`}>{step.icon}<span>{step.label}</span></div><div className="flex items-end justify-between"><span className="text-2xl font-semibold tracking-tight text-slate-900">{step.count}</span><span className="mb-1 text-[9px] text-slate-400">{step.sub}</span></div></div>{index < 3 && <ArrowRight size={14} className="hidden justify-self-center text-slate-300 sm:block"/>}{index < 3 && <ArrowDown size={14} className="mx-auto my-[-3px] text-slate-300 sm:hidden"/>}</div>)}</div>
            {!apiOnline && <p className="mt-4 text-[10px] leading-4 text-slate-400">Analysis and GitHub dispatch require the Motif API, database, and model/GitHub credentials. Your project sources are currently saved in this browser.</p>}
          </section>

          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_2px_8px_rgba(15,23,42,0.035)]">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 sm:px-6"><div><h2 className="text-sm font-semibold text-slate-900">Review the roadmap</h2><p className="mt-1 text-[11px] text-slate-500">Approve an evidence-backed theme to create its issue.</p></div><span className="rounded-full bg-slate-100 px-2 py-1 font-mono text-[10px] text-slate-600">{pendingThemes.length} to review</span></div>
            {pendingThemes.length ? <div className="divide-y divide-slate-100">{pendingThemes.map((theme) => <div key={theme.id} className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:px-6"><div className="flex min-w-0 flex-1 gap-3"><div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 font-mono text-xs text-amber-700">{(theme.cited_quotes || []).length}</div><div className="min-w-0"><h3 className="text-xs font-semibold text-slate-900">{theme.title}</h3><p className="mt-1 line-clamp-2 max-w-2xl text-[11px] leading-5 text-slate-500">{theme.summary}</p><div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500"><span>{theme.affected_accounts_count} accounts</span><span>·</span><span>${theme.revenue_at_risk.toLocaleString()} at risk</span><span>·</span><span>{(theme.cited_quotes || []).length} cited sources</span></div></div></div><div className="flex shrink-0 gap-2"><button onClick={() => setReviewTheme(theme)} className="rounded-lg border border-slate-200 px-3 py-2 text-[11px] text-slate-700 hover:bg-slate-100">Review evidence</button><button onClick={() => launchTheme(theme)} disabled={Boolean(working)} className="flex items-center gap-1.5 rounded-lg bg-[#0f766e] px-3 py-2 text-[11px] font-semibold text-white hover:bg-[#115e59] disabled:opacity-50">{working === theme.id ? <LoaderCircle size={13} className="animate-spin"/> : <Check size={13}/>} Launch issue</button></div></div>)}</div> : <div className="px-6 py-9 text-center"><p className="text-xs font-medium text-slate-700">{themes.length ? 'Nothing waiting for approval' : 'Your themes will appear here'}</p><p className="mt-1 text-[11px] text-slate-400">{themes.length ? 'New themes are ready after another analysis.' : 'Add sources, then analyze to discover what customers are telling you.'}</p></div>}
          </section>
        </>}
      </main>
    </div>

    {showCreate && <div className="modal-backdrop"><form onSubmit={createProject} className="modal-card"><div className="flex items-start justify-between"><div><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 text-[#0f766e]"><FolderKanban size={17}/></div><h2 className="text-lg font-semibold text-slate-900">Create a project</h2><p className="mt-1 text-xs leading-5 text-slate-500">Make a workspace for the feedback and roadmap you want to bring together.</p></div><button type="button" onClick={() => setShowCreate(false)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div><label className="mt-6 block text-[11px] font-medium text-slate-600">Project name<input autoFocus value={newName} onChange={(event) => setNewName(event.target.value)} className="field mt-2 w-full" placeholder="e.g. Project Atlas" required/></label><label className="mt-4 block text-[11px] font-medium text-slate-600">GitHub repository <span className="font-normal text-slate-400">(optional, owner/repo)</span><input value={newRepo} onChange={(event) => setNewRepo(event.target.value)} className="field mt-2 w-full" placeholder="acme/product"/></label><p className="mt-3 text-[10px] leading-4 text-slate-400">Projects and source metadata are stored in this browser. Issues use this project repository or fall back to the backend&apos;s configured repository.</p><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setShowCreate(false)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Cancel</button><button className="rounded-lg bg-[#0f766e] px-4 py-2 text-xs font-semibold text-white">Create project</button></div></form></div>}

    {showDrive && <div className="modal-backdrop"><form onSubmit={saveDriveScope} className="modal-card"><div className="flex items-start justify-between"><div><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><HardDrive size={17}/></div><h2 className="text-lg font-semibold text-slate-900">Add a Drive folder</h2><p className="mt-1 text-xs leading-5 text-slate-500">Scope this project to one folder, not your whole Drive.</p></div><button type="button" onClick={() => setShowDrive(false)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div><label className="mt-6 block text-[11px] font-medium text-slate-600">Google Drive folder URL or ID<input value={folderUrl} onChange={(event) => setFolderUrl(event.target.value)} className="field mt-2 w-full" placeholder="https://drive.google.com/drive/folders/…" required/></label><div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] leading-[1.7] text-slate-600"><span className="font-medium text-amber-800">Connector setup required.</span> This build does not have Google OAuth credentials or a Drive sync endpoint. The folder scope will be noted locally, but no Drive files are accessed yet. Enable the Google Drive connector on the backend before using it with sensitive project data.</div><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setShowDrive(false)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Cancel</button><button className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white">Save folder scope</button></div></form></div>}

    {reviewTheme && <div className="modal-backdrop"><div className="modal-card max-h-[85vh] overflow-y-auto"><div className="flex items-start justify-between"><div><span className="text-[10px] uppercase tracking-[.18em] text-[#0f766e]">Evidence review</span><h2 className="mt-2 text-lg font-semibold text-slate-900">{reviewTheme.title}</h2></div><button onClick={() => setReviewTheme(null)} className="text-slate-500 hover:text-slate-900"><X size={17}/></button></div><p className="mt-3 text-xs leading-5 text-slate-600">{reviewTheme.summary}</p><div className="mt-5 flex gap-4 border-y border-slate-200 py-3 text-[11px] text-slate-600"><span>${reviewTheme.revenue_at_risk.toLocaleString()} ARR at risk</span><span>{reviewTheme.affected_accounts_count} accounts</span></div><div className="mt-5 space-y-3">{reviewTheme.cited_quotes?.length ? reviewTheme.cited_quotes.map((quote, index) => <blockquote key={index} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-700">“{quote.quote_text}”<span className="mt-2 block text-[10px] text-slate-400">{quote.customer_id || 'Customer'}{quote.customer_tier ? ` · ${quote.customer_tier}` : ''}</span></blockquote>) : <p className="text-xs text-slate-500">No evidence quotes have been attached.</p>}</div><div className="mt-6 flex justify-end gap-2"><button onClick={() => setReviewTheme(null)} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">Close</button><button onClick={() => launchTheme(reviewTheme)} disabled={Boolean(working)} className="flex items-center gap-2 rounded-lg bg-[#0f766e] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"><GitBranch size={14}/> Approve & create issue</button></div></div></div>}
  </div>;
}
