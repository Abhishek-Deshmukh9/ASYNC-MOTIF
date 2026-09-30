# MOTIF

> **Your users already wrote the roadmap.**

[![Hackathon](https://img.shields.io/badge/ASYNC_2026-Open_Track-6366F1?style=flat-square)](https://async.hackathon)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active_Development-success?style=flat-square)]()

Motif is an automated feedback-to-backlog pipeline that ingests customer feedback across fragmented communication channels, discovers emergent themes using density clustering, ranks themes strictly by **"revenue at risk"**, and enforces a human Product Manager approval gate before automatically compiling a PRD and creating ready-to-sprint GitHub issues.

**Jump to:** [Setup & Installation](#12-setup--installation) · [Built Before vs. During ASYNC 2026](#13-built-before-vs-during-async-2026) · [Third-Party Code, Assets & AI Disclosure](#14-third-party-code-assets--ai-disclosure) · [License](#15-license)

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

1. **Centralizes Feedback:** Ingests reviews, emails and call transcripts into a unified data store.
2. **Discovers Unsupervised Themes:** Uses vector embeddings and HDBSCAN so themes emerge organically from data without human-biased pre-set taxonomies. Off-topic items are isolated as noise.
3. **Strict Quote Attribution:** An LLM (served by Groq, default `llama-3.3-70b-versatile`) labels each cluster against a strict Pydantic schema and must cite exact verbatim source quotes. Any quote that is not found word-for-word in the source feedback is discarded.
4. **Ranks by Revenue at Risk:** Each affected account's ARR is counted once, so one enterprise cancellation threat outranks 50 minor complaints from free users.
5. **Human Approval Gate:** A human PM reviews, approves or rejects proposed themes in a dedicated triage cockpit.
6. **Automated Shipping:** Approved themes become engineering-ready PRDs with Gherkin acceptance criteria, filed as GitHub issues.

---

## 3. How MOTIF Works

```text
Load Sources (Reviews, Support emails, Call transcripts, Uploaded docs, Recorded meetings)
       │
       ▼
Normalize & Deduplicate into one unified table (enriched with customer ARR/tier)
       │
       ▼
Generate Embeddings (all-MiniLM-L6-v2) & Cluster with HDBSCAN (outliers -> noise)
       │
       ▼
LLM Theme Synthesis & Strict Quote Attribution (Groq LLM + Pydantic schema)
       │
       ▼
Deterministic Verification (every quote must appear verbatim in its source)
       │
       ▼
Rank Discovered Themes by Revenue at Risk (each account counted once)
       │
       ▼
PM Triage Review Queue (PM approves or rejects)
       │
       ▼
Human PM Approves ──► Automated PRD Generation & GitHub Issue Creation
```

---

## 4. Key Features

- **Unified Connector Interface:** A standard connector base class. The MVP ingests app store reviews, support emails and call transcripts (JSON/CSV upload or the seed corpus). Slack, Notion and Google Drive connectors exist as **interface stubs only** — they enforce the privacy rules below but do not fetch live data yet.
- **Opt-in Privacy Scope:** Connectors only accept team-selected channels and folders; personal DMs and private folders are rejected.
- **Discovered Themes (Zero Predefined Categories):** Density clustering surfaces user friction without preconceived buckets.
- **Noise Handling:** Outliers and irrelevant feedback are isolated as noise rather than forced into artificial categories.
- **Verified Citations:** Every quote shown is checked word-for-word against the feedback it came from; the dashboard re-checks all stored quotes live.
- **Revenue at Risk Prioritization:** Prioritizes financial impact over complaint count.
- **Project Workspaces:** Separate project spaces with their own uploads, recorded meeting transcripts and themes, plus a pinned Demo benchmark workspace (see section 6).
- **PM Approval Gate:** The system proposes; the human PM decides. Nothing reaches GitHub without sign-off.
- **Backlog Delivery:** Approval produces a structured PRD and, when a GitHub token is configured, a real GitHub issue. Without a token the PRD is still generated and the UI states clearly that no issue was created.
- **Graceful Offline Mode:** Without any LLM API key, a deterministic offline labeler (which only quotes source text) is used so the pipeline still runs end to end.

---

## 5. Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Backend** | Python 3.11+, FastAPI |
| **Database & Vector Search** | PostgreSQL 16 + `pgvector` |
| **Embeddings** | `all-MiniLM-L6-v2` (Sentence Transformers, runs locally) |
| **Clustering** | HDBSCAN (`scikit-learn`) |
| **LLM Synthesis** | Groq API (default `llama-3.3-70b-versatile`, with automatic fallback to other Groq-hosted models); Gemini and OpenAI also supported; offline fallback |
| **Frontend Triage UI** | Next.js 16 + React 19 + Tailwind CSS 4 |
| **Infrastructure** | Docker Compose |
| **Integrations** | GitHub REST API (live when a token is set). Notion, Google Drive (service account), Slack and GitHub Issues: read-only connectors that sync into a project |

---

## 6. Project Workspaces and Intake

The triage UI has two kinds of workspace:

- **Demo benchmark** (pinned in the sidebar, opened by default on a first visit): the 300 labelled items loaded by `seed.py`, with the live quality metrics (P@3, acceptance rate, citation validity, ARR at risk). This is the workspace to use for judging and the demo.
- **Your own projects:** named project spaces with file and folder uploads, live browser meeting transcription, a source library, project-filtered theme analysis, evidence review, and a human-approved GitHub issue launch. Projects are listed in the browser; uploaded sources and their passages are stored in the database (`sources` and `feedback_items`), and each analysis only clusters that project's passages. Meeting transcripts are saved to the project library and downloaded as Markdown; captured audio is also downloaded as a WebM file. Live transcription uses the browser's SpeechRecognition implementation (Chrome or Edge recommended).

A project can target its own GitHub `owner/repo`; if none is set, the backend uses `GITHUB_REPO_OWNER` and `GITHUB_REPO_NAME`. Without `GITHUB_TOKEN`, approving a theme still generates its PRD and the UI states that no issue was created — Motif never invents issue URLs.

**Adding sources to a project.** Use **Upload files** or **Import folder** (for example an Obsidian vault). The backend reads:

| Format | How it is read |
| :--- | :--- |
| PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), HTML | Converted to Markdown with [MarkItDown](https://github.com/microsoft/markitdown), keeping headings, lists and tables |
| Markdown, text | Read directly; Obsidian front matter, `[[wiki links]]`, `![[embeds]]` and `%%comments%%` are cleaned up |
| CSV, JSON | If a column holds the feedback (`feedback`, `comment`, `message`, `text`, `review`…), each row becomes one item and `customer`, `plan`/`tier` and `arr`/`mrr` columns carry into revenue at risk. Otherwise the table is read as text |
| `.zip` | Every supported file inside is imported; hidden folders such as `.obsidian` are skipped |

Each document is split into passages of one idea each (a paragraph, a bullet point, a speaker's turn, a table row), up to about 900 characters so they fit the embedding model. Uploading the same content twice is detected and skipped. Scanned PDFs have no text layer and need OCR first. Limits: 25 MB per file, 100 files per request; the UI sends large folders in batches. Themes built from documents have no ARR attached, so they are ranked by how many passages mention them, and each quote shows the document it came from.

To try it, create a project and upload everything in [`data/demo-sources/`](data/demo-sources): an interview (Word), a renewal call transcript (Markdown), NPS comments (PDF), a business review (PowerPoint), a support-ticket export with ARR (CSV) and a small Obsidian vault (.zip). The same five problems appear across them in different words, so the analysis should group them into cross-source themes.

**Existing databases:** a fresh setup needs no extra step, because `scripts/init-db.sql` already includes the project columns. If your database was created before project workspaces were added, either reset it with `docker compose down -v` (this deletes its data), or add the columns with:

```bash
docker compose exec backend alembic stamp 001_initial_schema
```

```bash
docker compose exec backend alembic upgrade head
```

**Google Drive note:** The UI records a folder scope locally but does not yet authenticate to Google or sync Drive contents. `GoogleDriveConnector` is still a stub; Google OAuth credentials, token handling, folder listing/export, and a sync endpoint must be implemented before using this as a real Drive connection. The interface says so rather than claiming files were imported. To bring in Drive documents today, download them and use Upload files.

---

## 7. MVP Scope (ASYNC 2026 Deliverable)

- **Single-tenant** setup: issues go to the configured GitHub repository, or to a repository chosen per project.
- **Three core feedback sources** via one unified connector interface:
  1. Public app store reviews
  2. Sample customer support emails
  3. Sales/CS call transcripts
  *(Slack public channel connector as stretch goal).*
- **Demo Corpus:** 300 synthetic feedback items with account metadata (ARR and customer tier), generated by `seed.py`.
- **End-to-End Pipeline:** Ingest $\rightarrow$ Dedupe $\rightarrow$ Embed $\rightarrow$ Cluster $\rightarrow$ Label with Evidence $\rightarrow$ Rank by Revenue $\rightarrow$ Human PM Review $\rightarrow$ PRD + GitHub Issue.
- **Quality Benchmark:** Every item in the demo corpus carries a ground-truth theme label (`metadata.ground_truth_theme`), assigned by `seed.py` from the problem template the item was generated from. The label is never shown to the embedding, clustering or LLM steps.

---

## 8. Success Metrics & Target KPIs

All four metrics are computed live from the database by `GET /api/v1/metrics/eval` and shown in the **Demo benchmark** workspace. A metric shows "—" until there is something to measure.

| Metric | Target | How it is measured |
| :--- | :---: | :--- |
| **$P@3$ (Theme Precision at 3)** | $\ge 90\%$ | The 3 themes with the highest revenue at risk are each matched to the most common ground-truth label among their feedback items. $P@3$ is the share of those that match a *distinct* theme in the ground-truth top 3 (ground-truth themes ranked with the same revenue formula). |
| **As-is % (Acceptance Rate)** | $\ge 70\%$ | Share of PM decisions (approve/reject) that approved a theme without editing it. |
| **Pipeline Latency** | $< 90\text{s}$ | End-to-end processing time for 300 input items (target; depends on hardware and LLM provider). |
| **Citation Validity** | $100\%$ | Every stored quote is re-checked word-for-word against the feedback item it is attached to. |

---

## 9. Demo Flow

1. **Ingest Unseen Data:** Load 300 customer feedback items.
2. **Real-Time Processing:** The pipeline normalizes, embeds, clusters, labels, and ranks the items.
3. **Revenue at Risk Triage:** Present the ranked queue showing why Theme #1 is top-priority, with source quotes and customer ARR values.
4. **Live Validation Display:** The Demo benchmark workspace shows on-screen metrics: $P@3$ against the ground-truth labels, acceptance rate and citation validity.
5. **One-Click Ship:** The PM approves Theme #1; with `GITHUB_TOKEN` configured, a structured GitHub issue with the generated PRD, quotes, and acceptance criteria appears in the target repository.

---

## 10. Project Documentation

These planning documents were written **before** the hackathon (see [section 13](#13-built-before-vs-during-async-2026)). They describe the plan; where the implementation differs (for example, the LLM provider is Groq rather than GPT-4o-mini), this README is up to date.

- [Product Requirements Document (PRD)](./PRD.md) — Feature specifications, user personas, and acceptance benchmarks.
- [System Architecture](./Architecture.md) — Component diagrams, directory layout, data schema, and API contracts.
- [Development Rules & Axioms](./Rules.md) — Zero-hallucination policy, emergent discovery, and stack boundaries.
- [Implementation Roadmap & Phases](./Phases.md) — 5-phase breakdown from infrastructure setup to live demo.
- [Design System & UI Specs](./Design.md) — Triage cockpit layout, design tokens, and color scales.
- [Project Memory & Context](./Memory.md) — Planning-stage state tracker.

---

## 11. Future Scope

- **Live Slack, Notion and Google Drive connectors** (the interfaces exist as stubs today).
- **Multi-Tenant Enterprise Workspaces:** Multi-organization support with role-based access control (RBAC) and SSO.
- **Expanded Connector Ecosystem:** Zendesk, Intercom, Gong, Salesforce, and HubSpot integrations.
- **Bi-Directional Issue Trackers:** Native two-way synchronization with Linear and Jira.
- **Continuous Background Clustering:** Incremental real-time clustering rather than batch-triggered jobs.

---

## 12. Setup & Installation

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for PostgreSQL + pgvector). Open it once after installing, and wait for "Engine running".
- For local development (Option B): **Python 3.11+** and **Node.js 20.9+**.
- Internet access on the first pipeline run: the embedding model (~90 MB) is downloaded from Hugging Face.

### 1. Clone and configure

```bash
git clone https://github.com/Abhishek-Deshmukh9/ASYNC-MOTIF.git
cd ASYNC-MOTIF
cp .env.example .env
```

Everything runs with the defaults in `.env`. Optional settings:

| Variable | What it does |
| :--- | :--- |
| `GROQ_API_KEY` | Enables LLM theme labelling (free key at [console.groq.com](https://console.groq.com)). Without it, the deterministic offline labeler is used. |
| `GROQ_MODEL` | Groq model to try first (default `llama-3.3-70b-versatile`). |
| `LLM_PROVIDER` | `groq` (default), `gemini` or `openai`, with the matching `*_API_KEY`. |
| `GITHUB_TOKEN`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME` | Creates real GitHub issues on approval. Use a fine-grained token with **Issues: Read and write** on that one repository. Without all three, approval still generates the PRD, and the UI says no issue was created. |

### Option A — Run everything in Docker (simplest)

```bash
docker compose up -d --build
```

```bash
docker compose exec backend python seed.py
```

Then open **http://localhost:3000**. The **Demo benchmark** workspace opens on the first visit; click **Analyze demo feedback**. The API docs are at **http://localhost:8000/docs**.

### Option B — Local development (database in Docker, app on your machine)

Terminal 1 — database:

```bash
docker compose up -d postgres
```

Terminal 2 — backend (macOS/Linux; on Windows use `.venv\Scripts\activate`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py
uvicorn app.main:app --reload --port 8000
```

`python seed.py` should print `Successfully seeded 300 records`. If it says the database is not available, wait a few seconds for PostgreSQL to start and run it again. Running it again at any time resets the **Demo benchmark** (its feedback, themes and PM decisions) for a clean demo; your own project workspaces are not touched.

Terminal 3 — frontend:

```bash
cd triage-ui
npm install
npm run dev
```

Open **http://localhost:3000**, select **Demo benchmark** in the sidebar (it opens by default on a first visit) and click **Analyze demo feedback** (or call `POST /api/v1/pipeline/run` from http://localhost:8000/docs).

### Option C — Hosted database on Supabase

Supabase gives a hosted Postgres with pgvector, plus login and file storage used by upcoming features.

1. Create a Supabase project. In **SQL Editor** run `create extension if not exists vector;`.
2. From **Connect → Connection String**, copy the **Transaction pooler** (port 6543) and **Session pooler** (port 5432) URLs — not "Direct connection", which needs IPv6. In `.env` set:
   - `DATABASE_URL=` the transaction pooler URL, with `postgresql+asyncpg://` at the start
   - `SYNC_DATABASE_URL=` the session pooler URL (used for migrations)
3. Create the tables, then load the demo data (virtual environment active):

```bash
alembic upgrade head
```

```bash
python seed.py
```

4. Start the backend and frontend as in Option B (skip the Docker database step).

#### Sign-in (Supabase Auth)

With `SUPABASE_URL` set, the API requires a signed-in user and every project is private to the account that created it. To turn it on:

1. In Supabase, **Authentication → Sign In / Providers**: keep **Email** enabled. For a quick demo, turn **Confirm email** off so new accounts can sign in immediately.
2. Create `triage-ui/.env.local` with the browser-safe values (never the secret key):

```
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

3. Restart both servers. Opening the app now redirects to `/login`. The demo benchmark workspace (the 300 labelled items from `seed.py`) stays visible to every signed-in user; uploaded projects do not.

The backend verifies each token against the project's public signing keys (`/auth/v1/.well-known/jwks.json`); older HS256 projects can set `SUPABASE_JWT_SECRET`. Leave `SUPABASE_URL` empty, or set `AUTH_REQUIRED=false`, to run without accounts.

Row level security is enabled on every table, so the data is not reachable through Supabase's public API with the publishable key; the backend connects as the tables' owner and is unaffected.

### Connect Notion, Google Drive, Slack and GitHub Issues

Open a project and use **Connect your tools**. Each tool is read-only, tokens are encrypted before they are stored, and Motif reads only what you choose. **Sync now** adds new items, refreshes edited ones and removes deleted ones.

| Tool | What you need | What Motif reads |
| :--- | :--- | :--- |
| **Notion** | An internal integration secret from notion.so/profile/integrations. Share pages with it (page menu, Connections). | The pages shared with the integration, or only the ones you select. |
| **Google Drive** | A Google Cloud service account with the Drive API enabled; paste its JSON key. Share one folder with the service account email (Viewer). | That folder and its subfolders: Docs, Sheets, PDFs, Word, PowerPoint, Excel, Markdown. |
| **GitHub Issues** | A repository name (`owner/repo`). A token with read access to Issues only for private repositories. | Issues and their comments, not pull requests. |
| **Slack** | A Slack app with bot scopes `channels:read`, `channels:history`, `channels:join`, `users:read`, installed to the workspace; paste the `xoxb-` token. | The public channels you pick, last 90 days. Never DMs or private channels. |

Set `CONNECTOR_ENCRYPTION_KEY` in `.env` (any long random string; it falls back to `SUPABASE_SECRET_KEY`).

### Verify

```bash
curl http://localhost:8000/api/v1/health
```

### Run the tests

With the virtual environment active and the database running:

```bash
pip install pytest
pytest
```

### Troubleshooting

- **`docker: command not found`** — Docker Desktop is not installed or not open yet. Open it, wait for "Engine running", then restart your terminal.
- **Port 5432 already in use** — another PostgreSQL is running on your machine. Stop it, or change `POSTGRES_PORT` and the port in `DATABASE_URL` / `SYNC_DATABASE_URL` in `.env`.
- **First pipeline run is slow** — the embedding model is being downloaded; later runs are faster.
- **`column ... does not exist`** (for example `project_id` or `source_id`) — your database was created with an older schema. With the virtual environment active run `alembic upgrade head` (if Alembic says the tables already exist, run `alembic stamp 001_initial_schema` first), then `python seed.py`.
- **`Could not open requirements file`** — run the commands from the `ASYNC-MOTIF` folder (the one containing `requirements.txt`).

---

## 13. Built Before vs. During ASYNC 2026

| When | What | Commits |
| :--- | :--- | :--- |
| **Before the event** | Planning documents only: `PRD.md`, `Architecture.md`, `Rules.md`, `Phases.md`, `Design.md`, `Memory.md` and a first draft of this README. **No code was written before the event.** | `01b2e54` (24 Sep 2026) |
| **During the event** | All code: FastAPI backend, database schema and migrations, ingestion and normalization, embedding + HDBSCAN pipeline, LLM labelling with quote verification, revenue-at-risk ranking, PRD generator and GitHub dispatch, synthetic seed corpus, Next.js triage UI with project workspaces and meeting transcription, benchmark metrics, tests, Docker setup, and this README's setup, disclosure and license sections. | `22ef724` onwards |

---

## 14. Third-Party Code, Assets & AI Disclosure

**Starter code and generated files**
- `triage-ui/` was scaffolded with `create-next-app` (MIT). The config files, `public/*.svg`, `src/app/favicon.ico` and `triage-ui/README.md` come from that template. `triage-ui/AGENTS.md` and `CLAUDE.md` are generated automatically by `next dev`.

**Libraries** (installed from `requirements.txt` and `triage-ui/package.json`, not copied into the repo)
- Backend: FastAPI (MIT), SQLAlchemy (MIT), Alembic (MIT), asyncpg (Apache-2.0), pgvector-python (MIT), scikit-learn (BSD-3-Clause), sentence-transformers (Apache-2.0), httpx (BSD-3-Clause), Pydantic (MIT), MarkItDown (MIT) for document import, PyJWT (MIT) for verifying sign-in tokens, cryptography (Apache-2.0/BSD) for encrypting connector tokens.
- Frontend: Next.js (MIT), React (MIT), Tailwind CSS (MIT), lucide-react icons (ISC), supabase-js (MIT) for sign-in.

**Models, services and images**
- Embedding model: [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) (Apache-2.0), downloaded at runtime, not redistributed.
- Sign-in: Supabase Auth (hosted service; email and password).
- LLM: accessed through the Groq API (optionally Gemini or OpenAI); only the generated text is used.
- Database image: `pgvector/pgvector:pg16` (pgvector is under the PostgreSQL License).

**Dataset**
- `data/demo-sources/` is **synthetic** too: the companies (Kestrel Health, Brightline Freight, Halcyon Bank and others) and people in it are invented for this project.
- `data/seed/corpus_300.json` is **synthetic**, generated by `seed.py` for this project. Company and person names in it (Acme Global, Globex, Initech, etc.) are fictional placeholders. No real customer data is used.

**AI assistance**
- Parts of the code and documentation were written with the help of AI coding assistants: **Claude (Anthropic)** and **Gemini (Google Antigravity)**.

---

## 15. License

Released under the [MIT License](LICENSE).

---

## Team MOTIF (ASYNC 2026)

- **Track:** Open Track
- **Team Members:** 1MS24CS003 · 1MS24CS006 · 1MS24CS021
- **Team Lead:** Abhishek (1ms24cs006@msrit.edu)
