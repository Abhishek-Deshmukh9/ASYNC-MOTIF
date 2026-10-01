# Design System & UI Specification

## Project: **Motif**
> *Visual language, design tokens, component architecture, and interaction models for the high-density PM Triage Cockpit.*

---

## 1. Design Philosophy & Operational Cockpit Principles

Motif's interface is an **operational triage cockpit** engineered for product leaders, engineering managers, and founders. Unlike passive analytical dashboards or marketing portals, every pixel is optimized for high-speed decision-making, financial scrutiny, and rapid backlog delivery.

### Core Principles:
1. **High Information Density with Zero Clutter:** Scannability is paramount. An experienced PM should be able to evaluate 10 discovered themes, examine their customer tiers, and approve or reject issues in under 3 minutes without unnecessary visual padding.
2. **High-Trust Visual Authority:** Built on an intentional dark slate palette (`#0B0F17` base, `#111827` panels) accented with disciplined cobalt blues, emerald verification indicators, and muted crimson financial risk badges.
3. **Strict Boundary Between Synthesis and Ground Truth:**
   - **Sans-Serif (`Geist Sans` / `Inter`):** AI-synthesized titles, executive summaries, and generated acceptance criteria.
   - **Monospace (`JetBrains Mono` / `Geist Mono`):** Immutable ground-truth customer quotes, exact account ARR values, customer IDs, and file provenance paths.
4. **Dual Workspace Ergonomics:**
   - **Demo Benchmark Workspace:** Pinned in the sidebar for evaluation and hackathon judging; visualizes live $P@3$, As-is acceptance rate, citation validity, and the 300 curated benchmark signals.
   - **Custom Project Workspaces:** Dynamic spaces supporting multi-modal document uploads (Obsidian vaults, PDFs, Excel), browser audio recording, and custom repository targets.

---

## 2. Color Palette & Design Tokens

### 2.1 Theme Tokens (Tailwind CSS 4 Configuration)

```css
@theme {
  /* Surfaces & Structural Borders */
  --color-surface-base: #0B0F17;        /* Main viewport background */
  --color-surface-panel: #111827;       /* Card containers and sidebars */
  --color-surface-elevated: #1F2937;    /* Modals, popovers, and dialogs */
  --color-surface-border: #374151;      /* Crisp 1px structural dividing lines */
  --color-surface-border-subtle: #1E293B;

  /* High-Trust Primary (Indigo / Cobalt) */
  --color-primary-default: #3B82F6;     /* Primary interactive actions & CTA buttons */
  --color-primary-hover: #2563EB;       /* Focus and hover transitions */
  --color-primary-subtle: rgba(59, 130, 246, 0.12);

  /* Revenue at Risk & Churn Indicators */
  --color-risk-critical-text: #F87171;  /* High ARR exposure ($50,000+) */
  --color-risk-critical-bg: rgba(69, 10, 10, 0.40);
  --color-risk-critical-border: #7F1D1D;

  --color-risk-moderate-text: #FB923C;  /* Moderate ARR exposure ($10,000 - $50,000) */
  --color-risk-moderate-bg: rgba(67, 20, 7, 0.40);
  --color-risk-moderate-border: #7C2D12;

  --color-risk-low-text: #FBBF24;       /* Low ARR exposure (<$10,000) */
  --color-risk-low-bg: rgba(69, 26, 3, 0.30);
  --color-risk-low-border: #78350F;

  /* Deterministic Quote Verification (Emerald) */
  --color-verify-text: #10B981;         /* 100% Verbatim Quote Verified */
  --color-verify-bg: rgba(6, 78, 59, 0.30);
  --color-verify-border: #047857;

  /* High-Contrast Typography */
  --color-text-primary: #F9FAFB;       /* Headings, metrics, and primary labels */
  --color-text-secondary: #9CA3AF;     /* Problem summaries and user stories */
  --color-text-muted: #6B7280;         /* File paths, timestamps, metadata */
  --color-text-quote: #E2E8F0;         /* Ground-truth verbatim customer quotes */
}
```

---

## 3. Typography & Hierarchy

| Role | Font Family | Size / Weight | Line Height | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Cockpit Display** | Sans-Serif | `20px` / Bold (700) | `28px` | Main header, workspace title |
| **Card Header** | Sans-Serif | `15px` / SemiBold (600) | `22px` | Theme title, modal headings |
| **Financial Exposure** | Monospace | `14px` / Bold (700) | `20px` | ARR at Risk amounts (`$420,000`) |
| **Executive Summary** | Sans-Serif | `13px` / Regular (400) | `20px` | Synthesized problem description |
| **Evidence Quotes** | Monospace | `12px` / Regular (400) | `18px` | Verbatim source citations |
| **Meta Badges** | Monospace | `11px` / Medium (500) | `16px` | Customer tiers, $P@3$ KPIs, source tags |

---

## 4. Component Architecture & User Interactions

### 4.1 Cockpit Layout Decomposition (`src/app/page.tsx`)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [Motif Logo]  Workspace: [Demo Benchmark ▼]   [+ New Project]      [Live Health: DB Connected]  │
├───────────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ SIDEBAR               │ MAIN TRIAGE VIEWPORT                                                    │
│                       │                                                                         │
│ WORKSPACES            │ ┌─────────────────────────────────────────────────────────────────────┐ │
│ ★ Demo Benchmark      │ │ BENCHMARK HEALTH: P@3: 100% | As-Is Approval: 85% | Citation: 100%   │ │
│   (300 items)         │ └─────────────────────────────────────────────────────────────────────┘ │
│                       │                                                                         │
│ PROJECTS              │ [ Run Analysis ]  [ Upload Files ]  [ Import Vault ]  [ Record Meeting ]│
│ 📁 Q4 Enterprise Sync │                                                                         │
│ 📁 Mobile Beta        │ RANKED THEMES (Sorted by Revenue at Risk)                               │
│                       │ ┌─────────────────────────────────────────────────────────────────────┐ │
│ SOURCES & CONNECTIONS │ │ [1] Google Workspace SSO Token Expiration & Session Desync          │ │
│ ⚙ Manage Connectors   │ │     ARR at Risk: $420,000 | 4 Enterprise Accounts | 28 Passages      │ │
│ 👥 Share Project      │ │     Summary: Token expiration forces active editing logouts...       │ │
│                       │ │     Evidence:                                                       │ │
│                       │ │     ┌─────────────────────────────────────────────────────────────┐ │ │
│                       │ │     │ "If SSO session persistence isn't resolved by next month... │ │ │
│                       │ │     └─────────────────────────────────────────────────────────────┘ │ │
│                       │ │     [✓ 100% Verbatim Quote Verified]   Source: Acme_Call_Turn_4.md  │ │
│                       │ │     Actions: [ Approve & Ship to GitHub ]  [ Edit ]  [ Reject ]     │ │
│                       │ └─────────────────────────────────────────────────────────────────────┘ │
└───────────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Interactive Subsystems & Modals

1. **Multi-Source Document Uploader (`describeUpload`):**
   - Supports dragging and dropping batches up to 25 MB per file.
   - Converts Office documents, PDFs, and HTML into structured passages with immediate feedback on imported counts, duplicates skipped, and unsupported formats.
   - Direct Obsidian folder support (`webkitdirectory`) with front-matter and wiki-link cleanup.

2. **In-Browser Meeting Transcription (`SpeechRecognition` + Audio Recorder):**
   - Live speech-to-text transcript generation directly within the browser session.
   - Dual export: downloads live meeting transcript as formatted `.md` and simultaneously archives captured audio as `.webm`.

3. **Financial Impact & Score Breakdown (`ScoreBreakdown.tsx`):**
   - Interactive formula inspector showing whether a theme is ranked by:
     - **Revenue at Risk:** Sum of unique enterprise account ARRs.
     - **Mention Density:** Cross-document passage volume for unpriced documents.
     - **Combined Cohesion Score:** Mathematical breakdown preventing volume bias.

4. **Connectors Integration Manager (`Connectors.tsx`):**
   - Configuration modal for read-only enterprise tools: Notion, Google Drive, Slack, and GitHub Issues.
   - Clear disclosure badges distinguishing active parsers from upcoming interface stubs.

5. **Team Collaboration (`ShareProject.tsx`):**
   - Invite team members to project workspaces with permission levels (Admin, PM Editor, Viewer).

---

## 5. Accessibility, Motion & Quality Standards

- **Keyboard Navigation:** High-speed triage supports arrow key navigation through theme cards and quick approval shortcuts (`A` to approve, `R` to reject).
- **Subtle Micro-Animations:** Progress bars for embedding and clustering use smooth CSS transforms with zero layout thrashing.
- **Accessible Contrast:** All text tokens exceed WCAG AA 4.5:1 contrast requirements against their respective container backgrounds.
