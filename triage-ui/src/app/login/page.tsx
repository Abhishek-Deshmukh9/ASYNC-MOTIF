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

  return <main className="grid min-h-screen bg-paper lg:grid-cols-[minmax(0,1fr)_480px]">
    <section className="flex flex-col justify-between bg-chrome px-6 py-8 text-on-chrome sm:px-12 lg:py-14">
      <span className="text-[22px] font-bold tracking-[-0.02em] text-brand">motif</span>
      <div className="my-10 max-w-[34rem] lg:my-0">
        <h1 className="text-[34px] font-semibold leading-[1.1] tracking-[-0.02em] text-on-chrome sm:text-[44px]">Your users already wrote the roadmap.</h1>
        <p className="mt-4 max-w-[52ch] text-[16px] leading-relaxed text-on-chrome-muted">Motif reads your call notes, tickets and docs, groups what customers keep telling you, ranks it, and shows their exact words as proof before anything reaches your backlog.</p>
        <figure className="mt-8 hidden max-w-[34rem] rounded-lg bg-surface px-5 py-4 text-ink shadow-xl shadow-black/20 sm:block" aria-label="Example of a theme in Motif">
          <p className="text-[13px] text-muted">Example theme, ranked 1 of 12</p>
          <p className="mt-1 text-[16px] font-semibold text-ink">Exports drop rows without warning</p>
          <blockquote className="quote mt-2">“<span className="marked">Export to Excel drops rows without an error. We only noticed in an audit.</span>”</blockquote>
          <figcaption className="mt-1 text-[13px] text-muted">Enterprise customer, support ticket</figcaption>
        </figure>
      </div>
      <p className="hidden text-[13px] text-on-chrome-muted lg:block">Every quote is checked word for word against your sources.</p>
    </section>

    <section className="flex items-center border-t border-rule bg-surface px-6 py-10 sm:px-12 lg:border-l lg:border-t-0">
      <div className="mx-auto w-full max-w-sm">
        {!authEnabled ? <div>
          <h2 className="text-[20px] font-semibold text-ink">Sign-in is not set up</h2>
          <p className="mt-2 text-[14px] leading-relaxed text-muted">Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY to triage-ui/.env.local and restart the frontend. Until then Motif opens without accounts.</p>
          <button onClick={() => router.replace('/')} className="btn-primary mt-5">Open Motif</button>
        </div> : <form onSubmit={submit}>
          <h2 className="text-[20px] font-semibold text-ink">{mode === 'signin' ? 'Sign in' : 'Create your account'}</h2>
          <p className="mt-1 text-[14px] text-muted">{mode === 'signin' ? 'Your projects, and the ones shared with you.' : 'Projects you create are private until you share them.'}</p>
          <label className="mt-6 block text-[13px] font-medium text-ink">Email<input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="field mt-1.5 w-full" placeholder="you@company.com"/></label>
          <label className="mt-4 block text-[13px] font-medium text-ink">Password<input type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} className="field mt-1.5 w-full" placeholder="At least 6 characters"/></label>
          {error && <p role="alert" className="mt-4 rounded-md bg-danger-soft px-3 py-2 text-[13px] text-danger">{error}</p>}
          {info && <p role="status" className="mt-4 rounded-md bg-action-soft px-3 py-2 text-[13px] text-ink">{info}</p>}
          <button disabled={busy} className="btn-primary mt-6 w-full py-2.5">{busy && <LoaderCircle size={14} className="animate-spin"/>}{mode === 'signin' ? 'Sign in' : 'Create account'}</button>
          <p className="mt-4 text-center text-[13px] text-muted">{mode === 'signin' ? 'New to Motif? ' : 'Already have an account? '}<button type="button" onClick={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError(''); setInfo(''); }} className="font-medium text-link hover:underline">{mode === 'signin' ? 'Create an account' : 'Sign in'}</button></p>
        </form>}
      </div>
    </section>
  </main>;
}
