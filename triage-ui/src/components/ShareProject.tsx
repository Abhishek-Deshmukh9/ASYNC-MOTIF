'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Crown, LoaderCircle, LogOut, Trash2, UserPlus, X } from 'lucide-react';
import { changeMemberRole, fetchMembers, inviteMember, removeMember } from '@/utils/api';
import type { MemberList, ProjectRole } from '@/utils/types';

type Props = {
  projectId: string;
  projectName: string;
  myEmail: string;
  onClose: () => void;
  onLeft: () => void;   // the signed-in user removed themselves
};

const ROLE_HELP: Record<string, string> = {
  editor: 'Can upload, analyze, approve and reject',
  viewer: 'Can read themes and evidence only',
};

/** Who can work on this project. The owner invites by email and sets roles; anyone can see the list or leave.
 *  Mounted only while open, so every opening starts fresh. */
export default function ShareProject({ projectId, projectName, myEmail, onClose, onLeft }: Props) {
  const [list, setList] = useState<MemberList | null>(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Exclude<ProjectRole, 'owner'>>('editor');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  const load = useCallback(() => fetchMembers(projectId).then(setList).catch((cause) => setError(cause instanceof Error ? cause.message : 'Could not load members.')), [projectId]);
  useEffect(() => { load(); }, [load]);

  const isOwner = list?.my_role === 'owner';
  const me = myEmail.toLowerCase();

  const invite = async (event: FormEvent) => {
    event.preventDefault();
    setBusy('invite'); setError(''); setInfo('');
    try {
      const member = await inviteMember(projectId, email.trim(), role);
      setInfo(member.status === 'joined' ? `${member.email} has been added.` : `${member.email} is invited. The project appears for them when they sign in to Motif with this email.`);
      setEmail('');
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not invite.'); }
    finally { setBusy(''); }
  };

  const setMemberRole = async (id: string, next: Exclude<ProjectRole, 'owner'>) => {
    setBusy(id); setError('');
    try { await changeMemberRole(projectId, id, next); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not change the role.'); }
    finally { setBusy(''); }
  };

  const remove = async (id: string, memberEmail: string) => {
    const leaving = memberEmail === me;
    if (!window.confirm(leaving ? `Leave “${projectName}”? You will lose access until the owner invites you again.` : `Remove ${memberEmail} from “${projectName}”?`)) return;
    setBusy(id); setError('');
    try {
      await removeMember(projectId, id);
      if (leaving) { onLeft(); return; }
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not remove.'); }
    finally { setBusy(''); }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`Share ${projectName}`}>
      <div className="modal-card max-h-[85vh] overflow-y-auto" data-testid="share-dialog">
        <div className="flex items-start justify-between">
          <div>
                        <h2 className="text-[18px] font-semibold text-ink">Share “{projectName}”</h2>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{isOwner ? 'Invite teammates by email. They see this project when they sign in with that email.' : 'People who can work on this project.'}</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>
        </div>

        {isOwner && (
          <form onSubmit={invite} className="mt-5 flex flex-col gap-2 sm:flex-row">
            <input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="teammate@company.com" aria-label="Email to invite" className="field min-w-0 flex-1"/>
            <select value={role} onChange={(event) => setRole(event.target.value as 'editor' | 'viewer')} aria-label="Role" className="field py-2">
              <option value="editor">Editor</option>
              <option value="viewer">Viewer</option>
            </select>
            <button disabled={busy === 'invite' || !email.trim()} className="btn-primary">{busy === 'invite' ? <LoaderCircle size={13} className="animate-spin"/> : <UserPlus size={13}/>} Invite</button>
          </form>
        )}
        {isOwner && <p className="mt-2 text-[12px] leading-snug text-muted">Editor: {ROLE_HELP.editor.toLowerCase()}. Viewer: {ROLE_HELP.viewer.toLowerCase()}. Only you manage people and connected tools.</p>}

        {error && <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-[13px] text-danger">{error}</p>}
        {info && <p className="mt-3 rounded-md bg-action-soft px-3 py-2 text-[13px] text-ink">{info}</p>}

        <ul className="mt-5 divide-y divide-rule rounded-md border border-rule" data-testid="member-list">
          {!list ? <li className="px-3 py-4 text-center text-muted"><LoaderCircle size={14} className="mx-auto animate-spin"/></li> : <>
            <li className="flex items-center gap-3 px-3 py-2.5">
              <Crown size={15} className="shrink-0 text-muted"/>
              <div className="min-w-0 flex-1"><div className="truncate font-medium text-ink">{list.owner_email || 'Owner'}{list.owner_email === me && <span className="font-normal text-muted"> (you)</span>}</div><div className="text-[13px] text-muted">Owner, manages people and connected tools</div></div>
            </li>
            {list.members.map((member) => (
              <li key={member.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-ink">{member.email}{member.email === me && <span className="font-normal text-muted"> (you)</span>}</div>
                  <div className="text-[13px] text-muted">{member.status === 'joined' ? ROLE_HELP[member.role] : 'Invited, has not signed in yet'}</div>
                </div>
                {isOwner ? (
                  <select value={member.role} disabled={busy === member.id} onChange={(event) => setMemberRole(member.id, event.target.value as 'editor' | 'viewer')} aria-label={`Role for ${member.email}`} className="field py-1.5 text-[13px]">
                    <option value="editor">Editor</option>
                    <option value="viewer">Viewer</option>
                  </select>
                ) : <span className="text-[13px] capitalize text-muted">{member.role}</span>}
                {(isOwner || member.email === me) && (
                  <button onClick={() => remove(member.id, member.email)} disabled={busy === member.id} title={member.email === me ? 'Leave project' : 'Remove'} aria-label={member.email === me ? 'Leave project' : `Remove ${member.email}`} className="icon-btn hover:text-danger">
                    {member.email === me ? <LogOut size={13}/> : <Trash2 size={13}/>}
                  </button>
                )}
              </li>
            ))}
            {list.members.length === 0 && <li className="px-3 py-3 text-muted">No teammates yet.</li>}
          </>}
        </ul>

        <div className="mt-5 flex justify-end"><button onClick={onClose} className="btn-primary">Done</button></div>
      </div>
    </div>
  );
}
