# MOTIF

> **Your users already wrote the roadmap.**

[![Hackathon](https://img.shields.io/badge/ASYNC_2026-Open_Track-6366F1?style=flat-square)](https://async.hackathon)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active_Development-success?style=flat-square)]()

Motif is an automated feedback-to-backlog pipeline that ingests customer feedback across fragmented communication channels, discovers emergent themes using density clustering, ranks themes strictly by **"revenue at risk"**, and enforces a human Product Manager approval gate before automatically compiling a PRD and creating ready-to-sprint GitHub issues.

---

## 1. Problem Statement

Product teams collect far more feedback than they can ever process—app store reviews, support emails, sales-call recordings, customer Slack channels, and interview/call notes scattered across Notion and Google Drive. Nothing consolidates it into one place. 

As a result:
- **Prioritization collapses to recency and volume** rather than true value.
- **Engineering cycles are wasted** on guessed priorities.
- **Churn is silent:** Most unhappy customers never file multiple tickets—they simply stop paying. Feedback that never reaches prioritization is invisible revenue loss.
- **No evidence trail:** Teams cannot defend what they built or explain why critical requests were deprioritized.

---

## 2. Solution Overview

Motif does not just summarize—**it decides and ships**.

1. **Centralizes Feedback:** Ingests reviews, emails, call transcripts, Slack messages, and docs into a unified data store.
2. **Discovers Unsupervised Themes:** Uses vector embeddings and HDBSCAN so themes emerge organically from data without human-biased pre-set taxonomies. Off-topic items are isolated as noise.
3. **Strict Quote Attribution:** Employs an LLM (GPT-4o-mini) to label each cluster with strict schema adherence, citing exact verbatim source quotes.
4. **Ranks by Revenue at Risk:** One enterprise cancellation threat outranks 50 minor complaints.
5. **Human Approval Gate:** A human PM reviews, modifies, or rejects proposed themes in a dedicated triage cockpit.
6. **Automated Shipping:** Approved themes automatically become engineering-ready PRDs with acceptance criteria filed as GitHub issues.

---

## 3. How MOTIF Works

```text
Connect Sources (Reviews, Support Inboxes, Transcripts, Slack, Notion, Drive)
       │
       ▼
Normalize & Deduplicate into one unified table (enriched with customer ARR/tier)
       │
       ▼
Generate Embeddings (all-MiniLM-L6-v2) & Cluster with HDBSCAN (outliers -> noise)
       │
       ▼
LLM Theme Synthesis & Strict Quote Attribution (GPT-4o-mini + Pydantic Schema)
       │
       ▼
Deterministic Verification (100% Quote Check against source records)
       │
       ▼
Rank Discovered Themes by Estimated Revenue at Risk
       │
       ▼
PM Triage Review Queue (PM edits, adjusts, or rejects)
       │
       ▼
Human PM Approves ──► Automated PRD Generation & GitHub Issue Creation
```

---

## 4. Key Features

- **Plug-in Connectors:** Standardized connector interface ingestion across reviews, emails, transcripts, Slack, Notion, and Drive.
- **Opt-in Privacy Scope:** Only team-selected channels and folders are read; personal DMs and private folders are strictly excluded.
- **Discovered Themes (Zero Predefined Categories):** Mathematical density clustering surfaces true user friction without preconceived buckets.
- **Noise Handling:** Outliers and irrelevant feedback are isolated as noise rather than forced into artificial categories.
- **100% Verified Citations:** Every claim links directly to a real source quote; hallucination is detectable by script.
- **Revenue at Risk Prioritization:** Prioritizes financial impact over complaint count.
- **PM Approval Gate:** System proposes; the human PM decides. Nothing touches the production backlog without human sign-off.
- **Instant Backlog Delivery:** Output is a complete GitHub issue with a structured PRD and Gherkin acceptance criteria.

---

## 5. Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Backend** | Python, FastAPI |
| **Database & Vector Search** | PostgreSQL + `pgvector` |
| **Embeddings** | `all-MiniLM-L6-v2` (Sentence Transformers) |
| **Clustering** | HDBSCAN (`scikit-learn` / `hdbscan`) |
| **LLM Synthesis** | OpenAI `GPT-4o-mini` with Pydantic / JSON Schema |
| **Frontend Triage UI** | Next.js + Tailwind CSS |
| **Infrastructure** | Docker Compose |
| **Integrations** | Slack, Notion, Google Drive APIs, GitHub REST API |

---

## 6. Project workspaces and intake

The web workspace now supports named project spaces, project-scoped document uploads, live browser meeting transcription, a source library, project-filtered theme analysis, evidence review, and a human-approved GitHub issue launch. Project/source metadata is stored in the browser; uploaded content is sent to the API and tagged with its project ID. Meeting transcripts are saved to the project library and downloaded as Markdown; captured audio is also downloaded as a WebM file. Live transcription uses the browser's SpeechRecognition implementation (Chrome/Edge support is recommended).

For a local setup, run the database/API/UI with Docker Compose, then apply the project scoping migration:

```bash
docker compose up -d
docker compose exec backend alembic stamp 001_initial_schema
docker compose exec backend alembic upgrade head
```

The `stamp` step is for databases that were initialized by the app's existing `create_all()` startup path and have no Alembic version recorded. If your database is already tracked by Alembic, skip `stamp` and run only `alembic upgrade head`.

Configure your LLM and GitHub integration in `.env` (`GROQ_API_KEY` or another configured LLM provider, plus `GITHUB_TOKEN`, `GITHUB_REPO_OWNER`, and `GITHUB_REPO_NAME`). Set `GITHUB_TOKEN` on the backend. A project can target its own `owner/repo`; if none is set, the backend falls back to `GITHUB_REPO_OWNER` and `GITHUB_REPO_NAME`. Issue launch is disabled by an explicit API error until the token and destination are configured—Motif no longer invents simulated issue URLs.

**Google Drive note:** The current UI records a folder scope locally but does not yet authenticate to Google or sync Drive contents. `GoogleDriveConnector` is still a stub; Google OAuth credentials, token handling, folder listing/export, and a sync endpoint must be implemented before using this as a real Drive connection. The interface explicitly reports this rather than claiming files were imported. Uploaded files are currently parsed as text; binary Office/PDF extraction is not included.

---

## 7. MVP Scope (ASYNC 2026 Deliverable)

- **Single-tenant** setup targeting one GitHub repository.
- **Three core feedback sources** via one unified connector interface:
  1. Public app store reviews
  2. Sample customer support emails
  3. Sales/CS call transcripts
  *(Slack public channel connector as stretch goal).*
- **Demo Corpus:** 300 curated feedback items with account metadata (ARR and customer tier).
- **End-to-End Pipeline:** Ingest $\rightarrow$ Dedupe $\rightarrow$ Embed $\rightarrow$ Cluster $\rightarrow$ Label with Evidence $\rightarrow$ Rank by Revenue $\rightarrow$ Human PM Review $\rightarrow$ PRD + GitHub Issue.
- **Quality Benchmark:** Seeded 300-item evaluation benchmark with hand-labeled ground-truth themes and deduplication sets.

---

## 7. Success Metrics & Target KPIs

| Metric | Target | Description |
| :--- | :---: | :--- |
| **$P@3$ (Theme Precision at 3)** | $\ge 90\%$ | Top 3 discovered themes match a human reviewer's manual top 3 on the same corpus. |
| **As-is % (Acceptance Rate)** | $\ge 70\%$ | Share of proposed PRD tickets accepted by a PM without manual editing. |
| **Pipeline Latency** | $< 90\text{s}$ | End-to-end processing time for 300 input items. |
| **Citation Validity** | $100\%$ | Every generated claim cites a real input row—verified by script. |

---

## 8. Demo Flow

1. **Ingest Unseen Data:** Ingest 300 unread customer feedback items live on stage.
2. **Real-Time Processing:** The pipeline normalizes, embeds, clusters, labels, and ranks the items in under 90 seconds.
3. **Revenue at Risk Triage:** Present the ranked queue showing why Theme #1 is top-priority, with clickable source quotes and customer ARR values.
4. **Live Validation Display:** Real-time on-screen metrics showing clustering precision ($P@3$) against hand-labeled ground truth and acceptance rate.
5. **One-Click Ship:** The PM approves Theme #1 on stage; a structured GitHub issue with the generated PRD, quotes, and acceptance criteria appears immediately in the target repository.

---

## 9. Project Documentation

Comprehensive documentation is available in the project documentation directory:

- [Product Requirements Document (PRD)](./PRD.md) — Detailed feature specifications, user personas, and acceptance benchmarks.
- [System Architecture](./Architecture.md) — Component diagrams, monorepo directory layout, data schema, and API contracts.
- [Development Rules & Axioms](./Rules.md) — Zero-hallucination policy, emergent discovery, and stack boundaries.
- [Implementation Roadmap & Phases](./Phases.md) — 5-phase breakdown from infrastructure setup to live demo execution.
- [Design System & UI Specs](./Design.md) — Triage cockpit layout, design tokens, monospace quote treatments, and color scales.
- [Project Memory & Context](./Memory.md) — Living state tracker, engineering log, and immediate sprint tasks.

*(Note: For deployments with dedicated `/docs` hosting, see [docs/](./docs/)).*

---

## 10. Future Scope

- **Multi-Tenant Enterprise Workspaces:** Multi-organization support with role-based access control (RBAC) and SSO.
- **Expanded Connector Ecosystem:** Bi-directional Slack bot thread listening, Zendesk, Intercom, Gong, Salesforce, and HubSpot integrations.
- **Bi-Directional Issue Trackers:** Native two-way synchronization with Linear and Jira.
- **Continuous Background Clustering:** Incremental real-time clustering stream rather than batch-triggered jobs.

---

## 11. Setup & Installation (Placeholder)

> *Detailed setup instructions will be finalized in Phase 1 (Infrastructure Setup).*

```bash
# Clone the repository
git clone https://github.com/your-org/motif.git
cd motif

# Setup environment variables
cp .env.example .env

# Spin up local development environment (PostgreSQL + pgvector, FastAPI, Next.js)
docker compose up -d

# Verify backend health
curl http://localhost:8000/api/v1/health

# Access PM Triage Cockpit
open http://localhost:3000
```

---

## Team MOTIF (ASYNC 2026)

- **Track:** Open Track
- **Team Members:** 1MS24CS003 · 1MS24CS006 · 1MS24CS021
- **Team Lead:** Abhishek (1ms24cs006@msrit.edu)
