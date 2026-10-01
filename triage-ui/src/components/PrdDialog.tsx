'use client';

import { useState } from 'react';
import { Clipboard, ExternalLink, X } from 'lucide-react';
import type { Theme } from '@/utils/types';

type Props = {
  theme: Theme | null;
  onClose: () => void;
};

export default function PrdDialog({ theme, onClose }: Props) {
  const [copied, setCopied] = useState(false);

  if (!theme) return null;

  const copyPrd = async (markdown: string) => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Fallback: let user select and copy manually
    }
  };

  const downloadPrd = (markdown: string) => {
    const blob = new Blob([markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${theme.title.replace(/[^a-z0-9]+/gi, '_').toLowerCase()}_prd.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="PRD">
      <div className="modal-card max-h-[88vh] max-w-2xl overflow-y-auto">
        <div className="flex items-start justify-between gap-3">
          <div><p className="text-[13px] text-muted">PRD</p><h2 className="mt-0.5 text-[18px] font-semibold text-ink">{theme.title}</h2></div>
          <button onClick={onClose} aria-label="Close" className="icon-btn -mr-2 -mt-1"><X size={16}/></button>
        </div>

        {/* GitHub issue link — prominent banner */}
        {theme.github_issue_url ? (
          <a href={theme.github_issue_url} target="_blank" rel="noreferrer" className="mt-4 flex items-center gap-2 rounded-md bg-action-soft px-4 py-3 text-[13px] font-medium text-action hover:underline">
            <ExternalLink size={14}/>
            Issue #{theme.github_issue_number} is open in GitHub — view it
          </a>
        ) : (
          <p className="mt-4 rounded-md border-l-[3px] border-caution bg-caution-soft px-4 py-3 text-[13px] text-caution">Not sent to GitHub. To open real issues, set GITHUB_TOKEN, GITHUB_REPO_OWNER and GITHUB_REPO_NAME in the backend .env file.</p>
        )}

        <pre className="mt-4 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-md bg-paper p-4 font-mono text-[12.5px] leading-relaxed text-ink">{theme.prd_markdown || 'No PRD text came back for this theme.'}</pre>

        <div className="mt-5 flex flex-wrap justify-end gap-2">
          {theme.prd_markdown && <>
            <button onClick={() => downloadPrd(theme.prd_markdown!)} className="btn">↓ Download .md</button>
            <button onClick={() => copyPrd(theme.prd_markdown!)} className="btn"><Clipboard size={14}/>{copied ? 'Copied' : 'Copy PRD'}</button>
          </>}
          <button onClick={onClose} className="btn-primary">Done</button>
        </div>
      </div>
    </div>
  );
}
