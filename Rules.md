# Engineering & AI Operating Rules

## Project: **Motif**
> *Strict behavioral boundaries, technical constraints, and quality guardrails.*

---

## 1. Core System Axioms (Non-Negotiable)

### 1.1 The Zero-Hallucination & Quote Verification Rule
* **Rule:** An LLM may **never** synthesize a customer claim, feature request, or bug without attaching the exact verbatim source quote and customer ID from the ingested dataset.
* **Enforcement:**
  - Every theme payload must include `cited_quotes: List[str]`.
  - A deterministic validation filter executes before any theme is persisted or displayed:
    ```python
    def verify_quote(quote: str, raw_feedback_pool: List[str]) -> bool:
        return any(quote.strip() in item for item in raw_feedback_pool)
    ```
  - If a single quote fails verbatim substring matching, the cluster labeling fails and must be re-run or flagged with `citation_error`. Faith-based LLM summaries are strictly forbidden.

### 1.2 No Predefined Categories (Emergent Discovery Only)
* **Rule:** Developers and prompt engineers are strictly prohibited from hardcoding or guiding taxonomy categories (e.g., "UI/UX", "Billing", "Performance", "Authentication").
* **Enforcement:**
  - Clustering must be unsupervised, executed via **HDBSCAN** on semantic embeddings (`all-MiniLM-L6-v2`).
  - Clusters must reflect mathematical density in vector space.
  - Points with distance metrics exceeding cluster density thresholds must be assigned label `-1` (`Noise`) and discarded from theme generation. Under no circumstances should an outlier be forced into an artificial bucket.

### 1.3 Strict Human-in-the-Loop PM Approval Gate (No Auto-Shipping)
* **Rule:** The AI proposes; the human PM decides. Under no conditions shall the system automatically dispatch a PRD or create a GitHub issue without explicit PM interaction.
* **Enforcement:**
  - The backend GitHub dispatcher endpoint (`POST /api/v1/themes/{id}/approve`) must require an active PM approval signature and audit log entry.
  - Automated cron jobs or pipelines may only run up to the "Pending PM Review" state.
  - The UI must require the PM to physically review the quotes and click "Approve & Ship" (or edit/reject).

### 1.4 Revenue-First Ranking (Value Over Volume)
* **Rule:** Raw feedback frequency/count must never be the primary sort key.
* **Enforcement:**
  - Themes must be ranked by **Revenue at Risk** ($\sum \text{ARR} \times \text{Risk Multipliers}$).
  - A single enterprise account ($100k+ ARR) threatening churn must mathematically outrank 50 free-tier users requesting minor visual changes.

### 1.5 Strict Privacy & Opt-In Scoping
* **Rule:** Connectors must enforce an explicit opt-in boundary.
* **Enforcement:**
  - Personal DMs, unapproved private channels, and unselected folder trees must be blocked at the ingestion layer.
  - Unapproved inputs are discarded immediately in-memory and never written to PostgreSQL or vector storage.

---

## 2. Technical Stack Constraints

All development must strictly adhere to the defined technologies. Substituting these tools without formal architectural amendment is prohibited.

| Layer | Mandated Technology | Forbidden Alternatives |
| :--- | :--- | :--- |
| **Backend Framework** | **FastAPI (Python 3.11+)** | ❌ Flask, Django, Tornado, Express.js |
| **Database & Vectors** | **PostgreSQL 16 + pgvector** | ❌ Pinecone, Weaviate, Milvus, Chroma, SQLite |
| **Embedding Engine** | **Sentence-Transformers (`all-MiniLM-L6-v2`)** | ❌ OpenAI `text-embedding-3`, Cohere |
| **Clustering Engine** | **HDBSCAN (`scikit-learn` / `hdbscan`)** | ❌ K-Means (fixed $k$), DBSCAN (fixed epsilon), LDA |
| **LLM & Validation** | **GPT-4o-mini + Pydantic v2 JSON Schema** | ❌ Unstructured completions, Regex-only parsers |
| **Frontend UI** | **Next.js 14 (App Router) + TypeScript** | ❌ Create-React-App, Plain HTML/JS, Vue, Svelte |
| **Styling** | **Tailwind CSS** | ❌ Bootstrap, Material UI, plain CSS-in-JS |
| **Orchestration** | **Docker Compose** | ❌ Kubernetes (unnecessary for hackathon MVP) |
| **Issue Target** | **GitHub REST API v3** | ❌ Jira, Linear (MVP focus is single target) |

---

## 3. Code Quality & Architecture Conventions

### 3.1 Backend (FastAPI / Python)
1. **Type Annotations:** 100% type hint coverage. All API request and response bodies must be validated with Pydantic v2 schemas.
2. **Async Operations:** All I/O operations (PostgreSQL database queries, embedding generation calls, external API fetches) must be asynchronous (`async def`).
3. **Layer Separation:**
   - `connectors/`: Responsible strictly for network fetches, pagination, and normalization to `RawFeedback`.
   - `core/`: Pure computational logic (clustering, ranking, quote verification, PRD templating). No direct FastAPI request dependencies.
   - `api/`: Endpoint definitions, parameter validation, and dependency injection only.
   - `models/`: SQLAlchemy ORM models.
   - `schemas/`: Pydantic input/output validation models.
4. **Resilience & Timeouts:** All external HTTP calls (OpenAI, GitHub, Slack) must configure strict timeouts (maximum 15 seconds) and retry backoff.

### 3.2 Frontend (Next.js / TypeScript)
1. **TypeScript Strict Mode:** `"strict": true` enforced. No `any` types permitted in domain logic or API payloads.
2. **Server vs. Client Components:**
   - Prefer React Server Components (RSC) for initial page renders and static layouts.
   - Use Client Components (`"use client"`) strictly where stateful user interactions (modals, triage filters, PM editing, button triggers) occur.
3. **Data-Dense UI Design:** The PM triage interface is an operational cockpit, not a marketing website. Minimize whitespace, prioritize scannable tabular cards, highlight financial numbers, and display raw quotes in monospace callouts.

---

## 4. Evaluation & Testing Standards

1. **Benchmark Evaluation Suite:**
   - Every modification to clustering parameters (`min_cluster_size`, `min_samples`) or LLM prompts must be evaluated against the standard `data/seed/corpus_300.json`.
   - Benchmark targets:
     - **$P@3 \ge 90\%$** against ground truth hand-labeled clusters.
     - **Pipeline execution latency $< 90\text{ seconds}$** for 300 records.
     - **Citation validity $= 100\%$**.
2. **Unit & Integration Tests:**
   - Verification script unit test: Test that modified or hallucinated substrings are caught 100% of the time.
   - Deduplication test: Test that exact and near-duplicate inputs are consolidated before clustering.
   - Mocking external APIs: GitHub and OpenAI endpoints must have comprehensive mocks for offline testing.
