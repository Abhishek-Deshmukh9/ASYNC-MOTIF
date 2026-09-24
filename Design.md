# Design System & UI Specification

## Project: **Motif**
> *Visual language, design tokens, component architecture, and typography for a data-dense PM triage cockpit.*

---

## 1. Design Philosophy & Aesthetic Direction

Motif's interface is an **operational triage cockpit** for product leaders and founders, not a marketing landing page or consumer feed.

### Core Principles:
1. **High Information Density with Zero Clutter:** Prioritize scannability and compact layout over large empty gutters. A PM should be able to review 10 discovered themes without excessive scrolling.
2. **High-Trust Visual Authority:** Crisp lines, dark/neutral mode with deep slate tones, subtle borders, and intentional accents that convey precision, algorithmic rigor, and financial stakes.
3. **Monospace Raw Evidence Distinction:** A strict visual boundary separates AI synthesis from ground-truth evidence. AI-generated descriptions appear in crisp sans-serif, while verbatim customer quotes and customer identifiers always render in syntax-highlighted monospace containers.
4. **Financial Urgency Without Alarm Fatigue:** "Revenue at Risk" metrics use muted, sophisticated ember/crimson palettes rather than neon warning lights.

---

## 2. Color Palette & Design Tokens

### 2.1 Color Tokens (Tailwind Configuration)

```typescript
// tailwind.config.ts theme extension
export const themeColors = {
  // Backgrounds & Surface (Sleek deep slate)
  surface: {
    base: '#0B0F17',       // Main viewport background
    subtle: '#111827',     // Sidebars & card containers
    elevated: '#1F2937',   // Modals, popovers & elevated dropdowns
    border: '#374151',     // Subtle 1px structural borders
    borderSubtle: '#1E293B',
  },

  // High-Trust Primary (Indigo / Cobalt)
  primary: {
    DEFAULT: '#3B82F6',    // High-trust primary action
    hover: '#2563EB',      // Interactive hover state
    subtle: '#1D4ED820',   // Translucent active badges
    glow: 'rgba(59, 130, 246, 0.15)',
  },

  // Revenue-at-Risk & Churn Exposure (Muted Crimson / Ember)
  risk: {
    critical: {
      text: '#F87171',     // High-value churn text ($50k+)
      bg: '#450A0A50',     // Translucent dark red background
      border: '#7F1D1D',   // Deep crimson border
    },
    moderate: {
      text: '#FB923C',     // Mid-tier risk text ($10k-$50k)
      bg: '#43140750',     // Translucent amber background
      border: '#7C2D12',   // Muted amber border
    },
    low: {
      text: '#FBBF24',     // Low-tier risk (<$10k)
      bg: '#451A0340',     // Subtle warm yellow
      border: '#78350F',
    }
  },

  // Verification & Success (Emerald)
  success: {
    DEFAULT: '#10B981',    // 100% Citation verified badge
    subtle: '#064E3B40',
    border: '#047857',
  },

  // Typography Tokens
  text: {
    primary: '#F9FAFB',    // Highest contrast headings and primary labels
    secondary: '#9CA3AF',  // Body descriptions and metadata
    muted: '#6B7280',      // Timestamps, source types, fine print
    quote: '#E2E8F0',      // High-legibility quote text
  }
};
```

---

## 3. Typography & Hierarchy

### 3.1 Font Families
- **Primary Interface Font (Sans-Serif):** `Inter` or `Geist Sans`
  - Used for titles, summaries, buttons, badges, tables, and navigation.
  - Crisp optical sizing, high x-height for exceptional legibility at 12px–14px.
- **Evidence & Code Font (Monospace):** `JetBrains Mono` or `Geist Mono`
  - Used strictly for:
    - Verbatim customer quotes
    - Customer IDs and account ARR figures
    - GitHub issue IDs and Gherkin acceptance criteria
    - API latency and evaluation metrics

### 3.2 Type Scale

| Role | Font Family | Size / Weight | Line Height | Tracking |
| :--- | :--- | :--- | :--- | :--- |
| **Display / Header** | Sans-Serif | `20px` / Bold (700) | `28px` | `-0.02em` |
| **Section Title** | Sans-Serif | `16px` / SemiBold (600) | `24px` | `-0.01em` |
| **Card Heading** | Sans-Serif | `14px` / SemiBold (600) | `20px` | `normal` |
| **Body / Summary** | Sans-Serif | `13px` / Regular (400) | `18px` | `normal` |
| **Metadata & Badges** | Sans-Serif | `11px` / Medium (500) | `16px` | `+0.02em` (caps) |
| **Customer Quote** | Monospace | `12px` / Regular (400) | `18px` | `normal` |
| **Metric / Financial** | Monospace | `13px` / SemiBold (600) | `18px` | `normal` |

---

## 4. Key UI Components Specification

### 4.1 ThemeCard (`components/triage/ThemeCard.tsx`)
The centerpiece of the triage queue. Displays one discovered cluster.
- **Layout:** Compact horizontal card with a left-aligned priority badge, center title + summary, and right-aligned financial impact + actions.
- **Left Edge Border:** Color-coded border strip reflecting risk level:
  - Critical ($\ge \$50\text{k}$ ARR): `#7F1D1D` crimson strip.
  - Moderate ($\ge \$10\text{k}$ ARR): `#7C2D12` amber strip.
- **Header:** Theme title with cluster ID pill (e.g., `#CL-04`) and source distribution tag (e.g., `3 Sources · 14 Items`).
- **Body:** 2-line condensed synthesis of the customer friction point.
- **Footer:** Quick stats: Total ARR, Affected Accounts, and one featured quote preview.

### 4.2 RevenueRiskBadge (`components/triage/RevenueRiskBadge.tsx`)
Presents the financial exposure calculation in a high-urgency, professional pill.
```tsx
// Example Visual Output:
// [ 🔴 $142,500 at risk · 3 Enterprise Accounts ]
```
- **Styling:** Monospace bold text with muted crimson background (`#450A0A50`) and subtle red outline (`#7F1D1D`).
- **Hover Popover:** Shows breakdown:
  - Customer 1: Acme Corp ($90k ARR, Cancellation Risk: High)
  - Customer 2: Globex ($52.5k ARR, SLA Breach Risk)

### 4.3 QuoteInspector (`components/triage/QuoteInspector.tsx`)
The zero-hallucination verification window.
- **Design:** Dark slate code-block container with subtle rounded corners and 1px border.
- **Verified Icon:** Green checkmark badge (`100% Verbatim Verified`).
- **Quote Cards:**
  - Quote text in `font-mono text-xs text-slate-200` enclosed in quotation marks.
  - Context strip below quote: Source icon (App Store, Email, Call Transcript), Customer Name, Contract ARR, and Ingestion Timestamp.

### 4.4 ApprovalActionPanel (`components/triage/ApprovalActionPanel.tsx`)
The PM approval gate controls.
- **Secondary Actions:**
  - `Edit Theme`: Opens inline editor for title and description.
  - `Reject / Archive`: Muted button with confirmation popover.
- **Primary Action ("Approve & Ship"):**
  - High-contrast primary button (`bg-blue-600 hover:bg-blue-500 text-white font-medium`).
  - GitHub Octocat icon + text: `Approve & Create GitHub Issue`.
  - On click: Triggers micro-animation showing loading spinner $\rightarrow$ instant checkmark with link to live GitHub issue.

### 4.5 Live Benchmark Counter (`components/triage/LiveBenchmarkCounter.tsx`)
Persistent floating or top-bar status card displaying demo-day KPIs:
- `P@3: 94.2%` (vs. Hand-Labeled Ground Truth)
- `Accepted As-Is: 85%`
- `End-to-End Latency: 48s`
- `Citations: 100% Verified`

---

## 5. Layout & Grid Architecture

```text
+-----------------------------------------------------------------------------------+
|  [MOTIF]   Triage Queue    Benchmark Metrics: P@3: 94% | 100% Cites | <90s        |
+-----------------------------------------------------------------------------------+
| FILTERS: [All Sources v] [Min ARR: $10k v] [Cluster Status: Pending PM Review v]   |
+---------------------------------------------------+-------------------------------+
| DISCOVERED THEMES QUEUE (Ranked by Revenue Risk)  | EVIDENCE & PRD INSPECTOR      |
|                                                   |                               |
| [1] Enterprise SAML/SSO Login Failure Loop        | THEME #1: SAML SSO FAILURES   |
|     $142,500 at Risk · 3 Enterprise Accounts      | ----------------------------- |
|     "We literally cannot log in since Monday..."  | Revenue at Risk: $142,500     |
|     [Approve & Ship]  [Inspect]                   | Cohesion Score: 0.89          |
|                                                   |                               |
| [2] Silent Export Timeout on >50k Row Datasets    | GROUND TRUTH QUOTES (3 CITED) |
|     $86,000 at Risk · 2 Accounts                  | > "The export spinners run    |
|     "Our finance team's quarterly close failed..."|   forever and timeout at 60s" |
|     [Approve & Ship]  [Inspect]                   |   -- Acme Corp ($90k ARR)     |
|                                                   |                               |
| [3] Android 14 Bluetooth Background Crash         | PROPOSED GITHUB ISSUE PRD     |
|     $12,000 at Risk · 42 Reviews                  | Acceptance Criteria (Gherkin) |
|     "App crashes immediately on phone unlock..."  | [ EDIT PRD ] [ APPROVE & SHIP]|
+---------------------------------------------------+-------------------------------+
```

---

## 6. Micro-Interactions & Responsive Behavior

1. **Card Expansion:** Clicking any theme card smoothly focuses the right-hand Evidence & PRD Inspector without full page reload.
2. **Quote Highlighting:** Hovering over a claim in the PRD preview automatically highlights the exact source quote in the evidence panel.
3. **Approval State Transition:** When the PM clicks "Approve & Ship":
   - The card gently dims with a green checkmark badge: `Shipped to GitHub #142`.
   - The counter updates dynamically.
