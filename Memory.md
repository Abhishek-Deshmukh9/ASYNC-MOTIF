# Project Memory & Context Tracker

## Project Name: **Motif**
> *Living state, design decisions, execution history, and active milestones for ASYNC 2026 Hackathon.*

---

## 1. Project Overview & North Star
* **Product:** Motif — An automated feedback-to-backlog pipeline that ingests customer feedback, discovers emergent themes via density-based clustering, ranks themes strictly by "Revenue at Risk", and requires human PM approval before auto-compiling a PRD and filing a GitHub issue.
* **Tagline:** *"Your users already wrote the roadmap."*
* **Core Philosophy:** Motif does not just summarize; it decides and ships. It bridges the gap between raw, noisy user feedback and actionable engineering backlog tickets with zero hallucinations.

---

## 2. Foundational Files Log (All Generated)

| File | Status | Location & Purpose |
| :--- | :---: | :--- |
| **`PRD.md`** | ✅ Complete | [PRD.md](file:///c:/Users/abhis/Desktop/ASYNC/PRD.md) — Product requirements, user personas, problem definition, functional specs, and success metrics. |
| **`Architecture.md`** | ✅ Complete | [Architecture.md](file:///c:/Users/abhis/Desktop/ASYNC/Architecture.md) — 5-stage pipeline, monorepo directory layout, database schema with pgvector, and REST API endpoints. |
| **`Rules.md`** | ✅ Complete | [Rules.md](file:///c:/Users/abhis/Desktop/ASYNC/Rules.md) — Non-negotiable axioms: zero hallucinations, quote verification, dynamic HDBSCAN clustering, PM approval gate, tech stack constraints. |
| **`Phases.md`** | ✅ Complete | [Phases.md](file:///c:/Users/abhis/Desktop/ASYNC/Phases.md) — 5-phase execution plan: Infra $\rightarrow$ Ingestion $\rightarrow$ AI Engine $\rightarrow$ Triage UI $\rightarrow$ GitHub + Benchmark demo. |
| **`Design.md`** | ✅ Complete | [Design.md](file:///c:/Users/abhis/Desktop/ASYNC/Design.md) — Slate dark theme, high-trust blue, muted crimson revenue-at-risk badges, monospace quote inspector, and component blueprints. |
| **`Memory.md`** | ✅ Complete | [Memory.md](file:///c:/Users/abhis/Desktop/ASYNC/Memory.md) — Context memory, state tracking, and immediate execution milestones. |

---

## 3. Immutable Technical Stack & Constraints

* **Backend:** Python 3.11+ / FastAPI (Strictly asynchronous, full Pydantic v2 schemas).
* **Database & Vector Search:** PostgreSQL 16 + `pgvector` extension (Single datastore for relations and embeddings).
* **Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, local fast inference).
* **Clustering Algorithm:** `HDBSCAN` (via `scikit-learn` / `hdbscan`) — Density-based discovery; outliers assigned to noise (`-1`); no predefined categories.
* **LLM Engine:** OpenAI `GPT-4o-mini` with Pydantic JSON Schema enforcement.
* **Verification Filter:** 100% deterministic quote verification script checking verbatim substring presence against ingested feedback before persistence.
* **Frontend:** Next.js 14 (App Router) + TypeScript + Tailwind CSS.
* **Issue Tracker Target:** GitHub REST API v3.
* **Infrastructure:** Docker Compose.

---

## 4. Benchmark Targets for Demo Day

* **Theme Precision at 3 ($P@3$):** $\ge 90\%$ against ground truth hand-labeled clusters from `data/seed/corpus_300.json`.
* **PM Acceptance Rate (As-Is %):** $\ge 70\%$ of proposed PRDs accepted without text modification.
* **End-to-End Pipeline Latency:** $< 90\text{ seconds}$ for the 300-item evaluation set.
* **Citation Validity:** $100\%$ verified verbatim source quotes.

---

## 5. Active Sprint & Immediate Next Step

* **Current Status:** Foundation & planning phase successfully established.
* **Immediate Next Action:** **Start Phase 1: Infrastructure Setup**
  1. Create root `.env.example`, `.gitignore`, and `docker-compose.yml`.
  2. Define Docker configuration for `postgres` (with `pgvector`), `backend` (FastAPI), and `frontend` (Next.js).
  3. Initialize backend directory structure (`backend/app/...`), `pyproject.toml` / `requirements.txt`, and database connection test.
  4. Initialize frontend directory structure (`frontend/...`), `package.json`, and Tailwind CSS configuration.
  5. Verify `docker compose up -d` brings up all services cleanly with database vector support verified.
