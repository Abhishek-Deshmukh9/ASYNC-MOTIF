import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

// Sign-in is on only when both browser-safe values are set (see triage-ui/.env.local)
export const authEnabled = Boolean(url && publishableKey);

let client: SupabaseClient | null = null;
export function getSupabase(): SupabaseClient | null {
  if (!authEnabled) return null;
  if (!client) client = createClient(url as string, publishableKey as string);
  return client;
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
