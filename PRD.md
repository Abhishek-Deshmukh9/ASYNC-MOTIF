# Product Requirements Document (PRD)

## Project Name: **Motif**
> *"Your users already wrote the roadmap."*

---

## 1. Executive Summary
**Motif** is an autonomous feedback-to-backlog pipeline built for modern product teams. Rather than acting as another passive dashboard or generic summarizer, Motif ingests raw customer feedback from fragmented communication channels, discovers organic themes using density-based unsupervised clustering (HDBSCAN), ranks themes strictly by **"Revenue at Risk"**, and mandates a human-in-the-loop PM approval gate before automatically compiling a rigorous PRD and filing ready-to-sprint GitHub issues.

Every claim made by the system is bound to exact source quotes, establishing an immutable audit trail from user sentiment to code commit.

---

## 2. Problem Statement
Product teams at fast-growing software companies (5–500 employees) drown in fragmented customer feedback across disparate silos:
- App store reviews
- Customer support tickets & emails
- Sales & customer success call transcripts
- Public community or customer Slack channels
- Meeting notes and interview docs across Notion and Google Drive

### Core Symptoms:
1. **Recency & Volume Bias:** Product prioritization inevitably collapses to whoever screamed last or loudest, rather than what preserves the most business value.
2. **Silent Churn:** High-value enterprise accounts rarely file 50 repeated bug tickets—they mention a critical blocker once or twice and churn quietly when ignored.
3. **Wasted Engineering Sprints:** Engineering cycles—a startup's single most expensive capital expenditure—are squandered on guessed priorities.
4. **Lack of an Evidence Trail:** Teams cannot defend what they chose to build or explain why specific customer requests were deprioritized.

---

## 3. Target User Personas

| Persona | Role & Context | Pain Point Addressed |
| :--- | :--- | :--- |
| **Product Managers (Primary)** | Owns roadmap, sprint planning, and feature specs. | Spends days manually reading and tagging spreadsheets; struggles to justify prioritization to leadership. |
| **Founders / Executive Leadership** | Needs capital efficiency and revenue retention. | Watches ARR churn silently due to unaddressed customer friction; lacks visibility into true customer drivers. |
| **Support & Success Teams** | Manages frontline customer friction and renewals. | Repeats the same complaints month over month with zero roadmap leverage. |
| **Software Engineers** | Implements sprint deliverables. | Receives vague, poorly scoped feature tickets lacking user context or clear acceptance criteria. |
| **End Users / Enterprise Clients** | Relies on the software daily. | Experiences radio silence on critical business blockers and ultimately churns. |

---

## 4. Key Differentiators: What Makes Motif Unique

1. **Decides and Ships (Action-Oriented):** Not an analytical reporting tool or passive dashboard nobody opens. Motif's direct terminal output is an actionable, evidence-backed GitHub issue with acceptance criteria.
2. **Discovered Themes (Zero Predefined Taxonomies):** Motif does not force feedback into predefined, rigid buckets. Themes emerge organically from semantic density clusters via HDBSCAN.
3. **Revenue at Risk Prioritization:** Prioritizes by financial impact rather than raw count. One $120k/yr enterprise cancellation threat outranks 50 free-tier users complaining about button styling.
4. **Zero-Hallucination Evidence Trail:** Every assertion, pain point, and user persona cited in the synthesized theme is bound directly to an immutable source quote and customer identifier. Hallucinations are programmatically detectable.
5. **Human-in-the-Loop PM Gate:** AI proposes; the human PM decides. No ticket enters the production backlog without one-click approval, modification, or rejection by an authorized PM.
6. **Universal Connector Architecture:** Standardized ingestion schema ensures adding a new feedback source requires only a connector adapter, not a pipeline rewrite.

---

## 5. Functional Requirements & Feature Specifications

### 5.1 Ingestion & Scope Management
- **FR-1.1 Multi-Source Connectors:** Ingest text, metadata, timestamp, customer identifier, and contract ARR/tier from:
  - App Store / Public Reviews
  - Support Inboxes / Emails
  - Call Transcripts (sales/CS)
  - Selected Public Slack Channels
  - Notion / Google Drive folders
  - Direct CSV/JSON file uploads
- **FR-1.2 Strict Opt-In Scope:** Ingestion is strictly bounded to designated workspace channels and folders. Direct messages (DMs), private channels, and unselected directories are strictly ignored to ensure enterprise privacy.
- **FR-1.3 Normalization & Deduplication:** All inputs are normalized into a unified schema (`FeedbackItem`) and deduplicated via semantic and lexical fingerprinting.

### 5.2 Embedding & Unsupervised Discovery
- **FR-2.1 Dense Vector Embeddings:** Normalize feedback texts and generate high-dimensional embeddings using `all-MiniLM-L6-v2`.
- **FR-2.2 Density-Based Clustering (HDBSCAN):** Execute hierarchical density-based clustering to extract natural topic clusters.
- **FR-2.3 Noise Isolation:** Feedback items not belonging to dense clusters are categorized as `noise` rather than artificially forced into inappropriate themes.

### 5.3 LLM Synthesis & Evidence Citation
- **FR-3.1 Structured Theme Extraction:** Use `GPT-4o-mini` with Pydantic JSON Schema enforcement to parse each cluster.
- **FR-3.2 Grounded Quote Attribution:** The model must extract exact verbatim sub-strings from the cluster's items to justify:
  - Theme Title & Problem Description
  - Root Cause Analysis
  - Affected User Workflows
- **FR-3.3 Automated Citation Validation:** Automated script validation to verify that 100% of generated quotes exist verbatim within the ingested dataset.

### 5.4 Revenue at Risk Ranking Engine
- **FR-4.1 Impact Formula:** Calculate Theme Priority Score:
  $$\text{Priority Score} = \sum (\text{Account ARR} \times \text{Churn Intent Weight}) \times \text{Cluster Cohesion}$$
- **FR-4.2 Account Tier Fallbacks:** If ARR metadata is absent, tier default weights (Enterprise: $50k, Growth: $10k, Starter: $1k, Free: $0) are applied.
- **FR-4.3 Urgency Modifiers:** Churn indicators (e.g., "cancelling", "switching to competitor", "unusable", "breach of SLA") elevate risk weighting.

### 5.5 PM Triage Dashboard
- **FR-5.1 Ranked Queue:** Clean, high-density UI presenting discovered themes ordered by Revenue at Risk.
- **FR-5.2 Evidence Inspector:** Side-by-side view showing the synthesized problem, financial impact metrics, and raw verbatim user quotes with account metadata.
- **FR-5.3 PM Editing Controls:** The PM can edit the theme title, modify the proposed scope, reassign priority, or reject the theme.
- **FR-5.4 Approval Trigger:** A single "Approve & Ship" action triggers ticket compilation.

### 5.6 Automated PRD & GitHub Issue Dispatcher
- **FR-6.1 PRD Generation:** On approval, auto-compile a standardized mini-PRD containing:
  - Context & Customer Problem
  - User Evidence & Quotes
  - Revenue & Accounts at Risk
  - Technical Considerations & Proposed Scope
  - Verifiable Acceptance Criteria (Gherkin format / testable checkboxes)
- **FR-6.2 GitHub REST Integration:** Automatically creates a structured GitHub issue in the target repository with appropriate labels (`motif-approved`, `revenue-risk:critical`, `theme`).

---

## 6. Target Success Metrics & Acceptance Benchmarks

| Metric | Target | Verification Method |
| :--- | :--- | :--- |
| **Theme Precision @ 3 ($P@3$)** | $\ge 90\%$ | Top 3 system themes match a human senior PM's manual top 3 from the exact same evaluation corpus. |
| **PM Acceptance Rate (As-is %)** | $\ge 70\%$ | Percentage of proposed PRD tickets approved by the PM without text revisions. |
| **End-to-End Pipeline Latency** | $< 90\text{ seconds}$ | Clock time from initiating ingestion of 300 feedback items to full triage UI population. |
| **Citation Validity** | $100\%$ | Programmatic check verifying every quoted claim exists verbatim in the source database. |

---

## 7. MVP Scope vs. Future Roadmap

### In Scope for ASYNC 2026 MVP:
- Single-tenant workspace connected to one target GitHub repository.
- Connectors for 3 sources (App Store / CSV reviews, support emails, call transcripts).
- Seed evaluation corpus: 300 real/synthetic items with ground-truth hand-labeled themes and duplicate pairs.
- End-to-end pipeline: Ingest $\rightarrow$ Dedupe $\rightarrow$ Embed $\rightarrow$ HDBSCAN $\rightarrow$ LLM Synthesis $\rightarrow$ Revenue Rank $\rightarrow$ PM Triage UI $\rightarrow$ GitHub Issue Creation.
- Live validation display: Cluster quality score vs ground truth + unedited acceptance counter.

### Out of Scope for Initial MVP:
- Multi-tenant enterprise SSO / RBAC.
- Real-time bi-directional Slack bot thread listening (Public channel polling supported as stretch goal).
- Two-way sync with Jira / Linear (GitHub Issues is the canonical MVP target).
