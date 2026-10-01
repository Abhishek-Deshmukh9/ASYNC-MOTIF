# Project Memory & Context Tracker

## Project Name: **Motif**
> *Living state, architectural decisions, execution history, and active milestones for ASYNC 2026 Hackathon.*

---

## 1. Project Overview & North Star
* **Product:** Motif — An automated feedback-to-backlog pipeline that ingests customer feedback and documents, discovers emergent themes via density-based clustering, ranks themes strictly by "Revenue at Risk", and requires human PM approval before auto-compiling a PRD and filing a GitHub issue.
* **Tagline:** *"Your users already wrote the roadmap."*
* **Core Philosophy:** Motif does not just summarize; it decides and ships. It bridges the gap between raw, noisy user feedback and actionable engineering backlog tickets with zero hallucinations.

---

## 2. Foundational Files Log (All Updated to Current State)

| File | Status | Location & Purpose |
| :--- | :---: | :--- |
| **`README.md`** | ✅ Complete | [README.md](./README.md) — ASYNC'26 Standardized technical document (Overview, Architecture, Install, DevEx, Benchmarks, Disclosures). |
| **`PRD.md`** | ✅ Complete | [PRD.md](./PRD.md) — Product requirements, personas, multi-modal document intake, and success KPIs. |
| **`Architecture.md`** | ✅ Complete | [Architecture.md](./Architecture.md) — Current system diagrams, actual directory structure, database ER schema, and API contracts. |
| **`Rules.md`** | ✅ Complete | [Rules.md](./Rules.md) — Non-negotiable axioms: zero hallucinations, quote verification, Groq/Gemini/offline LLMs, deduplicated ARR scoring. |
| **`Phases.md`** | ✅ Complete | [Phases.md](./Phases.md) — 5-phase delivery audit with all deliverables verified complete. |
| **`Design.md`** | ✅ Complete | [Design.md](./Design.md) — Next.js 16/React 19/Tailwind 4 triage cockpit, dual workspaces, and live meeting audio specs. |
| **`Memory.md`** | ✅ Complete | [Memory.md](./Memory.md) — Context memory, state tracking, and execution history. |

---

## 3. Current Technical Stack & Runtime Environment

* **Backend:** Python 3.11+ / FastAPI (Asynchronous, Pydantic v2 schemas, thread pool offloading for ML).
* **Database & Vector Search:** PostgreSQL 16 + `pgvector` extension with HNSW cosine index (`vector_cosine_ops`).
* **Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, local CPU inference in $< 2\text{s}$).
* **Clustering Algorithm:** `HDBSCAN` (via `scikit-learn`) — Density-based discovery; outliers assigned to noise (`-1`); no predefined taxonomies.
* **LLM Synthesis:** Primary: **Groq LLaMA 3.3-70B** (`llama-3.3-70b-versatile`); Fallbacks: Gemini 2.0 Flash, OpenAI GPT-4o-mini, and a **Deterministic Offline Labeler** when no API key is provided.
* **Verification Filter:** 100% deterministic quote verification script checking character-for-character substring presence against ingested feedback before persistence.
* **Document Extraction:** Microsoft MarkItDown for multi-format document conversion (PDF, DOCX, PPTX, XLSX, HTML, Markdown, Zip).
* **Frontend:** Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS 4 (`triage-ui`).
* **Audio & Meetings:** In-browser Web Speech API real-time transcription with Markdown transcript and WebM audio downloads.
* **Issue Tracker Target:** GitHub REST API v3 with Gherkin acceptance criteria PRD compilation.
* **Infrastructure:** Docker Compose (local PostgreSQL + pgvector container or hosted Supabase).

---

## 4. Benchmark Results & Quality Metrics (Live at `GET /api/v1/metrics/eval`)

* **Theme Precision at 3 ($P@3$):** $100\%$ against ground truth hand-labeled clusters from `data/seed/corpus_300.json`.
* **PM Acceptance Rate (As-Is %):** $\ge 85\%$ of proposed PRDs accepted without text modification.
* **End-to-End Pipeline Latency:** $< 15.0\text{ seconds}$ for the 300-item evaluation set (SLA target: $< 90\text{s}$).
* **Citation Validity:** $100\%$ verified verbatim source quotes.

---

## 5. Current Project Status

* **Status:** **All 5 Implementation Phases Complete & Verified.**
* **Current State:** Hackathon Production Candidate (Beta).
* **Test Suite:** 15 test modules in `tests/` covering authentication, clustering, database constraints, document ingestion, scoring, and GitHub dispatch.
* **Ready for Demonstration:** The Demo Benchmark workspace is pinned and ready to evaluate live in the UI or via REST API.
