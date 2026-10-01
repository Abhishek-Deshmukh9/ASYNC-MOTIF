# Product Requirements Document (PRD)

## Project Name: **Motif**
> *"Your users already wrote the roadmap."*  
> Autonomous feedback-to-backlog triage prioritized by **Revenue at Risk**, backed by verified verbatim quotes, human PM governance, and 1-click GitHub backlog delivery.

---

## 1. Executive Summary
**Motif** is an autonomous feedback-to-backlog pipeline built for modern product and engineering teams. Rather than acting as another passive analytical dashboard or generic text summarizer, Motif ingests raw customer signals from fragmented channels and documents, discovers organic friction themes using density-based unsupervised clustering (HDBSCAN), ranks themes strictly by **"Revenue at Risk"**, and mandates a human-in-the-loop Product Manager approval gate before automatically compiling a rigorous PRD and filing ready-to-sprint GitHub issues.

Every claim made by the system is bound to exact source quotes, establishing an immutable audit trail from user sentiment to code commit with zero hallucinations.

---

## 2. Problem Statement
Product teams at fast-growing software companies drown in fragmented customer feedback across disparate silos:
- App store & public review portals
- Customer support tickets & email threads
- Sales & customer success call transcripts
- Uploaded office documents (Word, Excel, PowerPoint, PDF, Notion exports, Obsidian vaults)
- Live customer interview & renewal meeting recordings

### Core Symptoms:
1. **Recency & Volume Bias:** Product prioritization inevitably collapses to whoever screamed last or loudest, rather than what preserves the most business value.
2. **Silent Churn:** High-value enterprise accounts rarely file 50 repeated bug tickets—they mention a critical blocker once or twice and churn quietly when ignored.
3. **Wasted Engineering Sprints:** Engineering cycles—a startup's single most expensive capital expenditure—are squandered on guessed priorities.
4. **Lack of an Evidence Trail:** Teams cannot defend what they chose to build or explain why specific customer requests were deprioritized.

---

## 3. Target User Personas

| Persona | Role & Context | Pain Point Addressed |
| :--- | :--- | :--- |
| **Product Managers (Primary)** | Owns roadmap, sprint planning, and feature specs. | Spends days manually reading and tagging spreadsheets; struggles to defend prioritization decisions to executives. |
| **Founders / Executive Leadership** | Needs capital efficiency and revenue retention. | Watches ARR churn silently due to unaddressed customer friction; lacks visibility into true customer financial drivers. |
| **Support & Success Teams** | Manages frontline customer friction and renewals. | Escalates the same enterprise complaints month over month with zero roadmap leverage. |
| **Software Engineers** | Implements sprint deliverables. | Receives vague, poorly scoped feature tickets lacking user context or verifiable acceptance criteria. |
| **Enterprise Clients** | Relies on the software daily. | Experiences radio silence on critical business blockers and ultimately cancels six-figure contracts. |

---

## 4. Key Differentiators: What Makes Motif Unique

1. **Decides and Ships (Action-Oriented):** Not an analytical reporting tool or passive dashboard. Motif's output is an actionable, evidence-backed GitHub issue with acceptance criteria.
2. **Discovered Themes (Zero Predefined Taxonomies):** Motif does not force feedback into predefined, rigid buckets. Themes emerge organically from semantic density clusters via HDBSCAN.
3. **Revenue at Risk Prioritization:** Prioritizes by financial impact rather than raw count. One $120k/yr enterprise cancellation threat outranks 50 free-tier users complaining about button styling. Accounts are deduplicated so repeat tickets do not distort ARR.
4. **Zero-Hallucination Evidence Trail:** Every assertion, pain point, and user persona cited in the synthesized theme is bound directly to an immutable, character-for-character verified source quote and customer identifier.
5. **Human-in-the-Loop PM Gate:** AI proposes; the human PM decides. No ticket enters the production backlog without one-click approval, modification, or rejection by an authorized PM.
6. **Multi-Modal Document & Meeting Intake:** Ingests not only raw feedback rows, but full Word documents, PDFs, slide decks, spreadsheets, Obsidian vaults, and live in-browser meeting audio.
7. **Dual Workspace Ergonomics:** Provides a pinned Demo Benchmark workspace (300 pre-labeled items with live $P@3$ KPIs) and unlimited custom project workspaces targeting independent GitHub repositories.

---

## 5. Functional Requirements & Feature Specifications

### 5.1 Ingestion & Scope Management
- **FR-1.1 Multi-Source Connectors:** Ingest text, metadata, timestamp, customer identifier, and contract ARR/tier from:
  - App Store / Public Reviews
  - Support inboxes & email exports
  - Call transcripts (sales & customer success)
  - Direct file & folder uploads: PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), HTML, Markdown (`.md`), CSV, JSON, and Zip archives
  - Obsidian knowledge vaults via browser directory import (`webkitdirectory`)
- **FR-1.2 In-Browser Meeting Transcription:** Record live audio in the browser via Web Speech API, transcribe speaker turns in real time, and download transcript (`.md`) and audio (`.webm`).
- **FR-1.3 Strict Opt-In Scope:** Ingestion is strictly bounded to designated workspace channels and folders. Direct messages (DMs) and unselected directories are ignored.
- **FR-1.4 Normalization & Passage Chunking:** Ingested documents are parsed with Microsoft MarkItDown and chunked into coherent single-idea passages (~900 characters) matching speaker turns or paragraphs.

### 5.2 Embedding & Unsupervised Discovery
- **FR-2.1 Dense Vector Embeddings:** Normalize feedback texts and generate high-dimensional embeddings using `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, local inference).
- **FR-2.2 Density-Based Clustering (HDBSCAN):** Execute hierarchical density-based clustering to extract natural topic clusters without pre-set cluster counts ($k$).
- **FR-2.3 Noise Isolation:** Outlier data points are categorized as `noise` (cluster `-1`) rather than artificially forced into inappropriate themes.

### 5.3 LLM Synthesis & Evidence Citation
- **FR-3.1 Structured Theme Extraction:** Use **Groq LLaMA 3.3-70B** (with fallbacks to Gemini 2.0 Flash, OpenAI, or a deterministic offline labeler) with Pydantic JSON Schema enforcement.
- **FR-3.2 Grounded Quote Attribution:** The model must extract exact verbatim substrings from the cluster's items to justify:
  - Theme Title & Problem Description
  - Root Cause Analysis & Affected User Workflows
- **FR-3.3 Automated Citation Validation:** Deterministic string validator checks that 100% of generated quotes exist verbatim within the source database records. Non-matching quotes are rejected.

### 5.4 Revenue at Risk Ranking Engine
- **FR-4.1 Deduplicated Impact Formula:**
  $$\text{Revenue at Risk} = \sum_{a \in \text{Unique Accounts}} \text{ARR}_a \times \max_{i \in \text{Items}_a}(\text{Churn Multiplier}_i)$$
- **FR-4.2 Account Tier Fallbacks:** If ARR metadata is absent, tier default weights (Enterprise: $50k, Growth: $10k, Starter: $1k, Free: $0) are applied.
- **FR-4.3 Mention Density Mode:** For uploaded documents lacking explicit revenue columns, themes rank by passage volume and cross-source density.

### 5.5 PM Triage Cockpit
- **FR-5.1 Ranked Queue:** High-density UI presenting discovered themes ordered by Revenue at Risk.
- **FR-5.2 Evidence Inspector:** Modal showing the synthesized problem, financial impact metrics, and raw verbatim user quotes with source document provenance.
- **FR-5.3 PM Editing Controls:** The PM can edit the theme title, modify the proposed scope, or reject the theme.
- **FR-5.4 Approval Trigger:** A single "Approve & Ship" action logs the audit trail and dispatches the ticket.

### 5.6 Automated PRD & GitHub Issue Dispatcher
- **FR-6.1 PRD Generation:** On approval, auto-compile a standardized mini-PRD containing:
  - Context & Customer Problem
  - User Evidence & Quotes
  - Revenue & Accounts at Risk
  - Technical Considerations & Proposed Scope
  - Verifiable Acceptance Criteria in Gherkin syntax (`Given / When / Then`)
- **FR-6.2 GitHub REST Integration:** Creates a structured GitHub issue in the target repository with appropriate labels (`motif-approved`, `revenue-risk`, `theme`).

---

## 6. Success Metrics & Quality Benchmarks

| Metric | Target | Description |
| :--- | :---: | :--- |
| **$P@3$ (Precision at 3)** | $\ge 90\%$ | Top 3 revenue-ranked themes accurately match the top 3 ground-truth problem clusters in the benchmark corpus. |
| **As-Is PM Acceptance Rate** | $\ge 70\%$ | Share of PM decisions that approve themes without needing manual title edits. |
| **Pipeline Latency** | $< 90\text{s}$ | End-to-end execution for 300 input items (current implementation: $< 15\text{s}$). |
| **Citation Validity** | $100\%$ | Word-for-word string match of all persisted quotes against the raw feedback database. |
