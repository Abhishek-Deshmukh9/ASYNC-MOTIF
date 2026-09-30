'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LoaderCircle } from 'lucide-react';
import { authEnabled, getSupabase } from '@/utils/supabase';

// Turn Supabase's technical messages into something a person can act on
function friendly(message: string) {
  const text = message.toLowerCase();
  if (text.includes('invalid login')) return 'That email and password do not match. Check them, or create an account.';
  if (text.includes('already registered') || text.includes('already been registered')) return 'An account with this email already exists. Sign in instead.';
  if (text.includes('password') && (text.includes('least') || text.includes('short'))) return 'Use a password with at least 6 characters.';
  if (text.includes('rate limit') || text.includes('too many')) return 'Too many attempts. Wait a minute and try again.';
  if (text.includes('email') && text.includes('confirm')) return 'Confirm your email first: open the link we sent you, then sign in.';
  if (text.includes('fetch') || text.includes('network')) return 'Could not reach the sign-in service. Check your connection and try again.';
  return message;
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => { if (data.session) router.replace('/'); });
  }, [router]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const supabase = getSupabase();
    if (!supabase) return;
    setBusy(true); setError(''); setInfo('');
    try {
      if (mode === 'signin') {
        const { error: failure } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
        if (failure) throw failure;
        router.replace('/');
      } else {
        const { data, error: failure } = await supabase.auth.signUp({ email: email.trim(), password });
        if (failure) throw failure;
        if (data.session) router.replace('/');
        else setInfo('Account created. Check your email for a confirmation link, then sign in.');
      }
    } catch (failure) {
      setError(friendly(failure instanceof Error ? failure.message : 'Something went wrong. Try again.'));
    } finally { setBusy(false); }
  };

  return <main className="flex min-h-screen items-center justify-center bg-[#f4f6f8] px-4">
    <div className="w-full max-w-sm">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#0f766e] to-[#2ca58d] text-lg font-black text-white shadow-md shadow-emerald-900/15">m</div>
        <div><div className="text-lg font-semibold tracking-tight">motif</div><div className="text-xs text-slate-500">Your users already wrote the roadmap.</div></div>
      </div>
      {!authEnabled ? <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-base font-semibold text-slate-900">Sign-in is not set up</h1>
        <p className="mt-2 text-xs leading-5 text-slate-500">Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY to triage-ui/.env.local, restart the frontend, and this page will let you sign in. Until then Motif opens without accounts.</p>
        <button onClick={() => router.replace('/')} className="mt-4 rounded-lg bg-[#0f766e] px-4 py-2 text-xs font-semibold text-white">Open the workspace</button>
      </div> : <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-base font-semibold text-slate-900">{mode === 'signin' ? 'Sign in to Motif' : 'Create your account'}</h1>
        <p className="mt-1 text-xs text-slate-500">{mode === 'signin' ? 'Your projects are private to your account.' : 'Projects you create stay private to you.'}</p>
        <label className="mt-5 block text-[11px] font-medium text-slate-600">Email<input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="field mt-2 w-full" placeholder="you@company.com"/></label>
        <label className="mt-4 block text-[11px] font-medium text-slate-600">Password<input type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} className="field mt-2 w-full" placeholder="At least 6 characters"/></label>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
        {info && <p role="status" className="mt-4 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">{info}</p>}
        <button disabled={busy} className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-[#0f766e] px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-60">{busy && <LoaderCircle size={14} className="animate-spin"/>}{mode === 'signin' ? 'Sign in' : 'Create account'}</button>
        <button type="button" onClick={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError(''); setInfo(''); }} className="mt-4 w-full text-center text-xs text-slate-500 hover:text-slate-900">{mode === 'signin' ? 'New here? Create an account' : 'Already have an account? Sign in'}</button>
      </form>}
    </div>
  </main>;
}
